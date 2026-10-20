from __future__ import annotations

import subprocess
import sys
import uuid
from typing import Any

import httpx
import jwt

from tests.conftest import BACKEND_DIR, PASSWORD, World, make_providers, make_settings, new_workspace, register, running_app

API = "/api/v1"


async def test_register_login_and_me(client: httpx.AsyncClient) -> None:
    email = f"flow-{uuid.uuid4().hex[:6]}@example.com"
    created = await client.post(f"{API}/auth/register", json={"email": email, "password": PASSWORD})
    assert created.status_code == 201
    assert created.json()["token_type"] == "bearer"
    assert "password" not in created.text

    login = await client.post(f"{API}/auth/login", json={"email": email.upper(), "password": PASSWORD})
    assert login.status_code == 200  # emails are case-insensitive
    me = await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.json()["email"] == email


async def test_wrong_password_unknown_user_and_duplicates(client: httpx.AsyncClient) -> None:
    email, _ = await register(client)
    assert (await client.post(f"{API}/auth/login", json={"email": email, "password": "wrong-password"})).status_code == 401
    assert (
        await client.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    ).status_code == 401
    assert (await client.post(f"{API}/auth/register", json={"email": email, "password": PASSWORD})).status_code == 409
    assert (
        await client.post(f"{API}/auth/register", json={"email": "x@example.com", "password": "short"})
    ).status_code == 422
    assert (
        await client.post(f"{API}/auth/register", json={"email": "not-an-email", "password": PASSWORD})
    ).status_code == 422


async def test_expired_and_forged_tokens_are_rejected(client: httpx.AsyncClient, app: Any) -> None:
    settings = app.state.settings
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": 9999999999}, "another-secret-another-secret-12345", algorithm="HS256"
    )
    expired = jwt.encode({"sub": str(uuid.uuid4()), "exp": 1}, settings.jwt_secret, algorithm="HS256")
    unsigned = jwt.encode({"sub": str(uuid.uuid4()), "exp": 9999999999}, "", algorithm="none")
    for token in (forged, expired, unsigned):
        assert (await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401
    ghost = jwt.encode({"sub": str(uuid.uuid4()), "exp": 9999999999}, settings.jwt_secret, algorithm="HS256")
    assert (
        await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {ghost}"})
    ).status_code == 401  # valid token, deleted user


async def test_error_bodies_have_a_stable_shape_and_do_not_echo_input(client: httpx.AsyncClient) -> None:
    response = await client.post(f"{API}/auth/login", json={"email": "secret-value@example.com", "password": 123})
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"code", "detail"} and body["code"] == "invalid_input"
    assert "secret-value" not in response.text
    missing = await client.get(f"{API}/does-not-exist")
    assert missing.status_code == 404 and set(missing.json()) == {"code", "detail"}


async def test_security_headers_are_set(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


async def test_cors_allows_only_configured_origins(client: httpx.AsyncClient) -> None:
    allowed = await client.options(
        f"{API}/auth/login", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    blocked = await client.options(
        f"{API}/auth/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in blocked.headers


async def test_health_and_metrics(client: httpx.AsyncClient, world: World) -> None:
    health = await client.get("/healthz")
    assert health.json() == {"status": "ok", "database": True}
    await client.post(
        f"{API}/ask",
        json={"workspace_id": world.workspace_id, "question": "How many unused PTO days can I carry over?"},
        headers=world.employee,
    )
    metrics = (await client.get("/metrics")).text
    for name in (
        "citesure_ask_total",
        "citesure_stage_latency_seconds",
        "citesure_job_queue_depth",
        "citesure_claims_dropped_total",
    ):
        assert name in metrics


async def test_login_attempts_are_rate_limited(pg_url: str, storage_dir: str) -> None:
    settings = make_settings(pg_url, storage_dir, rate_limit_auth_per_min=3)
    async with running_app(settings, make_providers(storage_dir)) as limited_app:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=limited_app), base_url="http://test") as c:
            codes = [
                (await c.post(f"{API}/auth/login", json={"email": "a@example.com", "password": "whatever-1"})).status_code
                for _ in range(5)
            ]
    assert codes == [401, 401, 401, 429, 429]


async def test_ask_is_rate_limited_per_user(pg_url: str, storage_dir: str) -> None:
    settings = make_settings(pg_url, storage_dir, rate_limit_ask_per_min=2)
    async with running_app(settings, make_providers(storage_dir)) as limited_app:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=limited_app), base_url="http://test") as c:
            workspace_id, admin, _ = await new_workspace(c)
            body = {"workspace_id": workspace_id, "question": "anything at all?"}
            codes = [(await c.post(f"{API}/ask", json=body, headers=admin)).status_code for _ in range(3)]
            other_workspace, other_admin, _ = await new_workspace(c)
            other = await c.post(
                f"{API}/ask", json={"workspace_id": other_workspace, "question": "hello there?"}, headers=other_admin
            )
    assert codes == [200, 200, 429]
    assert other.status_code == 200  # another user has their own budget


def test_migrations_match_the_models(pg_url: str) -> None:
    """`alembic check` fails if the SQLAlchemy models changed without a migration."""
    import os

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": pg_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
