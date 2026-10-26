"""OIDC sign-in end to end (real Postgres, mocked identity provider: nothing touches the network)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from sqlalchemy import text

from app.services.oidc import OidcClient
from tests.conftest import PASSWORD, make_providers, make_settings, new_workspace, register, running_app
from tests.idp import CLIENT_ID, ISSUER, REDIRECT, MockIdp

API = "/api/v1"


@dataclass
class Browser:
    client: httpx.AsyncClient
    idp: MockIdp
    app: Any

    async def sign_in(self, *, tamper_state: bool = False, drop_cookie: bool = False) -> tuple[str | None, str | None]:
        """Run the whole redirect dance; returns (token, error code) from the final fragment."""
        start = await self.client.get(f"{API}/auth/oidc/login")
        assert start.status_code == 302
        location = urlparse(start.headers["location"])
        assert location.netloc == "idp.test"
        query = {k: v[0] for k, v in parse_qs(location.query).items()}
        self.idp.last_nonce = query["nonce"]
        if drop_cookie:
            self.client.cookies.clear()
        state = "forged-state" if tamper_state else query["state"]
        done = await self.client.get(f"{API}/auth/oidc/callback", params={"code": "abc", "state": state})
        assert done.status_code == 302
        fragment = parse_qs(urlparse(done.headers["location"]).fragment)
        return (fragment.get("oidc_token") or [None])[0], (fragment.get("oidc_error") or [None])[0]


@asynccontextmanager
async def browser(pg_url: str, storage_dir: str, idp: MockIdp, **overrides: Any) -> AsyncIterator[Browser]:
    settings = make_settings(
        pg_url,
        storage_dir,
        oidc_enabled=True,
        oidc_issuer=ISSUER,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret="not-a-real-secret",
        oidc_redirect_uri=REDIRECT,
        **overrides,
    )
    async with running_app(settings, make_providers(storage_dir)) as app:
        app.state.oidc = OidcClient(settings, idp.client())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
            yield Browser(client, idp, app)


def unique(prefix: str = "sso") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@acme.example"


async def me(client: httpx.AsyncClient, token: str) -> dict[str, Any]:
    response = await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_it_is_off_by_default(client: httpx.AsyncClient) -> None:
    config = (await client.get(f"{API}/auth/config")).json()
    assert config == {"password_login": True, "registration": True, "oidc_enabled": False, "oidc_provider_name": None}
    assert (await client.get(f"{API}/auth/oidc/login")).status_code == 404
    assert (await client.get(f"{API}/auth/oidc/callback", params={"code": "x", "state": "y"})).status_code == 404


async def test_the_login_redirect_sets_a_locked_down_cookie_and_the_config_offers_the_button(
    pg_url: str, storage_dir: str
) -> None:
    async with browser(pg_url, storage_dir, MockIdp(), oidc_provider_name="Acme Keycloak") as b:
        config = (await b.client.get(f"{API}/auth/config")).json()
        assert config["oidc_enabled"] is True and config["oidc_provider_name"] == "Acme Keycloak"
        assert config["password_login"] is True  # local sign-in stays unless OIDC_ONLY
        start = await b.client.get(f"{API}/auth/oidc/login")
        cookie = start.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "secure" in cookie
        assert "path=/api/v1/auth/oidc" in cookie and "max-age=600" in cookie
        assert start.headers["cache-control"] == "no-store"


async def test_first_login_creates_the_account_when_allowed_and_reuses_it_afterwards(pg_url: str, storage_dir: str) -> None:
    idp = MockIdp()
    email = unique()
    idp.claims = {"email": email}
    async with browser(pg_url, storage_dir, idp, oidc_auto_create_users=True) as b:
        token, error = await b.sign_in()
        assert error is None and token
        first = await me(b.client, token)
        assert first["email"] == email
        again, _ = await b.sign_in()
        assert again and (await me(b.client, again))["id"] == first["id"]
        # the account has no password anyone knows
        assert (await b.client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})).status_code == 401
        async with b.app.state.sessionmaker() as session:
            identities = (
                await session.execute(text("SELECT count(*) FROM oidc_identities WHERE user_id = :u"), {"u": first["id"]})
            ).scalar_one()
            logins = (
                (
                    await session.execute(
                        text(
                            "SELECT metadata FROM audit_log WHERE action = 'auth.oidc_login' AND actor_id = :u ORDER BY seq"
                        ),
                        {"u": first["id"]},
                    )
                )
                .scalars()
                .all()
            )
        assert identities == 1 and [m["new_account"] for m in logins] == [True, False]


async def test_unknown_people_are_refused_unless_auto_create_is_on(pg_url: str, storage_dir: str) -> None:
    idp = MockIdp()
    idp.claims = {"email": unique("stranger")}
    async with browser(pg_url, storage_dir, idp) as b:
        token, error = await b.sign_in()
        assert token is None and error == "no_account"
        async with b.app.state.sessionmaker() as session:
            reason = (
                await session.execute(
                    text(
                        "SELECT metadata->>'reason' FROM audit_log WHERE action = 'auth.oidc_failed' ORDER BY seq DESC LIMIT 1"
                    )
                )
            ).scalar_one()
        assert reason == "no_account"


async def test_an_existing_local_account_is_linked_by_verified_email_only(pg_url: str, storage_dir: str) -> None:
    idp = MockIdp()
    async with browser(pg_url, storage_dir, idp) as b:
        email, headers = await register(b.client, "local")
        user_id = (await b.client.get(f"{API}/auth/me", headers=headers)).json()["id"]
        idp.claims = {"email": email.upper(), "sub": "linked-subject"}
        token, error = await b.sign_in()
        assert error is None and token and (await me(b.client, token))["id"] == user_id  # case-insensitive match

        # an unverified address would let anyone claim a colleague's account, so it is refused (a fresh subject: no link yet)
        idp.claims = {"email": email, "email_verified": False, "sub": "someone-else"}
        assert await b.sign_in() == (None, "email_unverified")
        idp.claims, idp.drop = {"sub": "no-email-subject"}, {"email"}
        assert await b.sign_in() == (None, "no_email")
        idp.claims, idp.drop = {"email": email, "email_verified": "false", "sub": "str-subject"}, set()
        assert await b.sign_in() == (None, "email_unverified")


async def test_groups_are_mapped_only_to_existing_groups_and_only_provider_grants_are_revoked(
    pg_url: str, storage_dir: str
) -> None:
    idp = MockIdp()
    email = unique("grp")
    idp.claims = {"email": email}
    async with browser(pg_url, storage_dir, idp, oidc_auto_create_users=True) as b:
        token, _ = await b.sign_in()  # creates the account, which has no workspace yet
        assert token
        workspace_id, admin, _ = await new_workspace(b.client)
        added = await b.client.post(
            f"{API}/workspaces/{workspace_id}/members", json={"email": email, "role": "member"}, headers=admin
        )
        assert added.status_code == 201
        groups = {}
        for name in ("hr", "finance", "legal"):
            groups[name] = (
                await b.client.post(f"{API}/workspaces/{workspace_id}/groups", json={"name": name}, headers=admin)
            ).json()["id"]
        await b.client.post(f"{API}/groups/{groups['legal']}/members", json={"email": email}, headers=admin)  # by hand

        async def membership() -> set[str]:
            listed = (await b.client.get(f"{API}/workspaces/{workspace_id}/groups", headers=admin)).json()
            uid = (await me(b.client, token))["id"]
            return {g["name"] for g in listed if uid in g["member_ids"]}

        idp.claims = {"email": email, "groups": ["/hr", "ghost-group", "legal"]}
        assert (await b.sign_in())[0]
        assert await membership() == {"hr", "legal"}  # hr granted; "ghost-group" does not exist, so it is not created
        listed = (await b.client.get(f"{API}/workspaces/{workspace_id}/groups", headers=admin)).json()
        assert {g["name"] for g in listed} == {"hr", "finance", "legal"}

        idp.claims = {"email": email, "groups": ["finance"]}
        assert (await b.sign_in())[0]
        assert await membership() == {"finance", "legal"}  # hr revoked; legal was added by an admin and stays

        idp.claims = {"email": email, "groups": []}
        assert (await b.sign_in())[0]
        assert await membership() == {"legal"}


async def test_state_cookie_signature_and_audience_failures_never_yield_a_token(pg_url: str, storage_dir: str) -> None:
    idp = MockIdp()
    idp.claims = {"email": unique()}
    async with browser(pg_url, storage_dir, idp, oidc_auto_create_users=True) as b:
        assert await b.sign_in(tamper_state=True) == (None, "bad_state")
        assert await b.sign_in(drop_cookie=True) == (None, "no_flow")
        idp.claims = {**idp.claims, "aud": "someone-elses-client"}
        assert await b.sign_in() == (None, "bad_id_token")
        idp.claims = {"email": unique()}
        idp.nonce_override = "replayed"
        assert await b.sign_in() == (None, "bad_nonce")
        idp.nonce_override = None
        idp.token_status = 400
        assert await b.sign_in() == (None, "token_exchange_failed")
        idp.token_status = 200
        denied = await b.client.get(f"{API}/auth/oidc/callback", params={"error": "access_denied", "state": "x"})
        assert unquote(denied.headers["location"]).endswith("oidc_error=provider_access_denied")
        missing = await b.client.get(f"{API}/auth/oidc/callback")
        assert unquote(missing.headers["location"]).endswith("oidc_error=bad_request")
        assert "secret detail" not in denied.text + missing.text


async def test_oidc_only_switches_password_sign_in_and_registration_off(pg_url: str, storage_dir: str) -> None:
    async with browser(pg_url, storage_dir, MockIdp(), oidc_only=True) as b:
        config = (await b.client.get(f"{API}/auth/config")).json()
        assert config["password_login"] is False and config["registration"] is False and config["oidc_enabled"] is True
        login = await b.client.post(f"{API}/auth/login", json={"email": "a@acme.example", "password": PASSWORD})
        register_ = await b.client.post(f"{API}/auth/register", json={"email": "b@acme.example", "password": PASSWORD})
        assert login.status_code == 403 and register_.status_code == 403
