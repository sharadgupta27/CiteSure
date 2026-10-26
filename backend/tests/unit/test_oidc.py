"""OIDC client against a mocked identity provider (httpx.MockTransport + a locally generated RSA key)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from app.config import Settings
from app.services.oidc import OidcClient, OidcError, extract_groups, pkce_challenge
from tests.idp import CLIENT_ID, ISSUER, REDIRECT, MockIdp, make_key


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "env": "test",
        "oidc_enabled": True,
        "oidc_issuer": ISSUER,
        "oidc_client_id": CLIENT_ID,
        "oidc_client_secret": "not-a-real-secret",
        "oidc_redirect_uri": REDIRECT,
        "jwt_secret": "test-secret-test-secret-test-secret",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


async def start(idp: MockIdp, **overrides: object) -> tuple[OidcClient, str, str, str]:
    """Begin a flow and return (client, state, nonce, cookie), as the browser round trip would."""
    client = OidcClient(make_settings(**overrides), idp.client())
    state, nonce, verifier = client.new_flow()
    await client.authorization_url(state, nonce, verifier)
    idp.last_nonce = nonce
    return client, state, nonce, client.flow_cookie(state, nonce, verifier)


async def test_authorization_url_carries_pkce_state_and_nonce() -> None:
    idp = MockIdp()
    client = OidcClient(make_settings(), idp.client())
    state, nonce, verifier = client.new_flow()
    url = urlparse(await client.authorization_url(state, nonce, verifier))
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.netloc == "idp.test"
    assert query["response_type"] == "code" and query["client_id"] == CLIENT_ID and query["redirect_uri"] == REDIRECT
    assert query["state"] == state and query["nonce"] == nonce
    assert query["code_challenge_method"] == "S256" and query["code_challenge"] == pkce_challenge(verifier)
    assert verifier not in url.query  # the verifier itself never goes to the browser or the provider's front channel


async def test_a_valid_login_returns_verified_claims_and_sends_the_verifier_to_the_token_endpoint() -> None:
    idp = MockIdp()
    idp.claims = {"groups": ["/hr", "finance"]}
    client, state, _, cookie = await start(idp)
    claims = await client.complete("the-code", state, cookie)
    assert claims.email == "alice@acme.example" and claims.email_verified is True
    assert claims.subject == idp.subject and claims.issuer == ISSUER
    assert claims.groups == ["finance", "hr"]  # Keycloak's leading slash is stripped
    form = idp.token_requests[0]
    assert form["grant_type"] == "authorization_code" and form["code"] == "the-code"
    assert form["redirect_uri"] == REDIRECT and form["client_id"] == CLIENT_ID
    assert form["code_verifier"] and form["client_secret"] == "not-a-real-secret"


async def test_state_mismatch_and_missing_or_forged_cookie_are_refused() -> None:
    idp = MockIdp()
    client, state, _, cookie = await start(idp)
    with pytest.raises(OidcError) as bad_state:
        await client.complete("c", "another-state", cookie)
    assert bad_state.value.reason == "bad_state"
    with pytest.raises(OidcError) as missing:
        await client.complete("c", state, None)
    assert missing.value.reason == "no_flow"
    forged = jwt.encode(
        {"typ": "oidc_flow", "state": state, "nonce": "n", "verifier": "v", "exp": time.time() + 99}, "x" * 40
    )
    with pytest.raises(OidcError):
        await client.complete("c", state, forged)
    session_token = jwt.encode(  # a normal CiteSure session token is not a flow cookie
        {"sub": "u", "exp": time.time() + 99}, "test-secret-test-secret-test-secret", algorithm="HS256"
    )
    with pytest.raises(OidcError):
        await client.complete("c", state, session_token)
    assert idp.token_requests == []  # nothing was exchanged


async def test_wrong_nonce_is_refused() -> None:
    idp = MockIdp()
    idp.nonce_override = "replayed-nonce"
    client, state, _, cookie = await start(idp)
    with pytest.raises(OidcError) as error:
        await client.complete("c", state, cookie)
    assert error.value.reason == "bad_nonce"


@pytest.mark.parametrize(
    ("claims", "drop"),
    [
        ({"iss": "https://evil.test/realms/acme"}, set()),
        ({"aud": "another-client"}, set()),
        ({"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}, set()),
        ({}, {"exp"}),
        ({}, {"sub"}),
        ({}, {"iat"}),
        ({"aud": [CLIENT_ID, "other"]}, set()),  # several audiences without azp
    ],
)
async def test_id_tokens_with_bad_claims_are_refused(claims: dict[str, object], drop: set[str]) -> None:
    idp = MockIdp()
    idp.claims, idp.drop = claims, drop
    client, state, _, cookie = await start(idp)
    with pytest.raises(OidcError) as error:
        await client.complete("c", state, cookie)
    assert error.value.reason == "bad_id_token"


async def test_a_token_signed_with_someone_elses_key_is_refused() -> None:
    idp = MockIdp()
    idp.sign_with = make_key()  # same kid, different key
    client, state, _, cookie = await start(idp)
    with pytest.raises(OidcError) as error:
        await client.complete("c", state, cookie)
    assert error.value.reason == "bad_id_token"


async def test_hs256_signed_with_the_public_key_is_refused() -> None:
    """The classic algorithm-confusion attack: HS256 with the RSA public key as the HMAC secret. PyJWT refuses to
    build such a token, so it is assembled by hand."""
    idp = MockIdp()
    client, state, nonce, cookie = await start(idp)
    public_pem = idp.key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def part(data: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    now = int(time.time())
    signing_input = (
        part({"alg": "HS256", "typ": "JWT", "kid": idp.kid})
        + "."
        + part({"iss": ISSUER, "aud": CLIENT_ID, "sub": "s", "iat": now, "exp": now + 99, "nonce": nonce})
    )
    signature = base64.urlsafe_b64encode(hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()).rstrip(b"=")
    with pytest.raises(OidcError) as error:
        await client.verify_id_token(signing_input + "." + signature.decode(), nonce)
    assert error.value.reason == "bad_id_token"


async def test_alg_none_is_refused() -> None:
    idp = MockIdp()
    client, state, nonce, cookie = await start(idp)
    unsigned = jwt.encode(
        {"iss": ISSUER, "aud": CLIENT_ID, "sub": "s", "exp": time.time() + 99, "nonce": nonce}, None, algorithm="none"
    )
    with pytest.raises(OidcError):
        await client.verify_id_token(unsigned, nonce)


async def test_an_unknown_key_id_triggers_one_refetch_then_fails() -> None:
    idp = MockIdp()
    client, state, _, cookie = await start(idp)
    await client.complete("c", state, cookie)  # warms the key cache
    jwks_fetches = sum(1 for r in idp.requests if r.url.path.endswith("/certs"))
    idp.kid = "rotated"  # the provider signs with a key id the cache has never seen... and publishes it
    state2, nonce2, verifier2 = client.new_flow()
    idp.last_nonce = nonce2
    claims = await client.complete("c", state2, client.flow_cookie(state2, nonce2, verifier2))
    assert claims.subject == idp.subject
    assert sum(1 for r in idp.requests if r.url.path.endswith("/certs")) == jwks_fetches + 1


async def test_token_endpoint_errors_do_not_leak_provider_details() -> None:
    idp = MockIdp()
    idp.token_status = 400
    client, state, _, cookie = await start(idp)
    with pytest.raises(OidcError) as error:
        await client.complete("c", state, cookie)
    assert error.value.reason == "token_exchange_failed" and "secret detail" not in error.value.detail


async def test_metadata_with_a_different_issuer_is_refused() -> None:
    idp = MockIdp()
    idp.metadata_issuer = "https://idp.test/realms/other"
    client = OidcClient(make_settings(), idp.client())
    with pytest.raises(OidcError) as error:
        await client.metadata()
    assert error.value.reason == "bad_metadata"


async def test_unreachable_provider_is_a_clean_error() -> None:
    import httpx

    def refuse(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    client = OidcClient(make_settings(), httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    with pytest.raises(OidcError) as error:
        await client.metadata()
    assert error.value.reason == "provider_unreachable"


def test_extract_groups_handles_lists_strings_paths_and_junk() -> None:
    assert extract_groups({"groups": ["a", "/b", 3, None, "a"]}, "groups") == ["a", "b"]
    assert extract_groups({"groups": "solo"}, "groups") == ["solo"]
    assert extract_groups({"realm_access": {"roles": ["r1"]}}, "realm_access.roles") == ["r1"]
    assert extract_groups({}, "groups") == [] and extract_groups({"groups": {"x": 1}}, "groups") == []


# --- settings checks ----------------------------------------------------------------------
def test_oidc_settings_are_validated_at_boot() -> None:
    make_settings().assert_safe_for_prod()
    with pytest.raises(RuntimeError, match="OIDC_ONLY"):
        Settings(env="test", oidc_only=True).assert_safe_for_prod()
    with pytest.raises(RuntimeError, match="OIDC_CLIENT_ID"):
        make_settings(oidc_client_id="").assert_safe_for_prod()
    with pytest.raises(RuntimeError, match="https"):
        make_settings(oidc_issuer="http://idp.example.com/realms/acme").assert_safe_for_prod()
    make_settings(oidc_issuer="http://keycloak:8080/realms/acme").assert_safe_for_prod()  # private network: http is fine


def test_private_mode_needs_the_provider_on_a_private_network() -> None:
    with pytest.raises(RuntimeError, match="PRIVATE_MODE"):
        make_settings(private_mode=True, llm_provider="local").assert_safe_for_prod()
    make_settings(
        private_mode=True, llm_provider="local", oidc_issuer="http://keycloak:8080/realms/acme"
    ).assert_safe_for_prod()


def test_vault_without_a_key_refuses_to_boot() -> None:
    with pytest.raises(RuntimeError, match="VAULT"):
        Settings(env="test", vault_enabled=True).assert_safe_for_prod()
