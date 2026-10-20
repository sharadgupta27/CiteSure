"""Shared fixtures. Integration tests start a real Postgres + pgvector with testcontainers (Docker required) and run
the real Alembic migrations against it. Everything else is fake: LLM, embeddings, reranker (CLAUDE.md testing rules)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.embeddings.fake import FakeEmbedder, LexicalReranker
from app.llm.fake import FakeProvider
from app.main import create_app
from app.providers import Providers
from app.seed import SeedResult, seed_demo
from app.storage.base import LocalBlobStore
from app.worker import drain

BACKEND_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "citesure-demo"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")  # one fewer image to pull
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        "pgvector/pgvector:pg16", username="citesure", password="citesure", dbname="citesure", driver="asyncpg"
    ) as container:
        url = container.get_connection_url()
        env = {**os.environ, "DATABASE_URL": url}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR, env=env, check=True)
        yield url


@pytest.fixture(scope="session")
def storage_dir() -> Iterator[str]:
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


def make_settings(pg_url: str, storage_dir: str, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "env": "test",
        "database_url": pg_url,
        "storage_path": storage_dir,
        "jwt_secret": "test-secret-test-secret-test-secret",
        "rate_limit_ask_per_min": 10_000,
        "rate_limit_auth_per_min": 10_000,
        "chunk_tokens": 400,
    }
    return Settings(**{**base, **overrides})


def make_providers(storage_dir: str) -> Providers:
    return Providers(FakeProvider(), FakeEmbedder(), LexicalReranker(), LocalBlobStore(storage_dir))


@asynccontextmanager
async def running_app(settings: Settings, providers: Providers) -> AsyncIterator[Any]:
    app = create_app(settings, providers=providers)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture(scope="session")
async def app(pg_url: str, storage_dir: str) -> AsyncIterator[Any]:
    async with running_app(make_settings(pg_url, storage_dir), make_providers(storage_dir)) as application:
        yield application


@pytest.fixture(scope="session")
async def client(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_llm(app: Any) -> Iterator[None]:
    """Tests may swap in a misbehaving fake model; always restore the well-behaved one."""
    original = app.state.providers.llm
    yield
    app.state.providers.llm = original


@dataclass
class World:
    """The seeded Acme company: three users and two collections, one of them HR-only."""

    seed: SeedResult
    workspace_id: str
    general_id: str
    confidential_id: str
    admin: dict[str, str]
    employee: dict[str, str]
    hr: dict[str, str]


async def login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
async def world(app: Any, client: httpx.AsyncClient) -> World:
    seed = await seed_demo(app.state.sessionmaker, app.state.providers, app.state.settings, password=PASSWORD)
    return World(
        seed=seed,
        workspace_id=str(seed.workspace_id),
        general_id=str(seed.general_id),
        confidential_id=str(seed.confidential_id),
        admin=await login(client, "admin@acme.example"),
        employee=await login(client, "employee@acme.example"),
        hr=await login(client, "hr@acme.example"),
    )


async def register(client: httpx.AsyncClient, prefix: str = "user") -> tuple[str, dict[str, str]]:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return email, {"Authorization": f"Bearer {response.json()['access_token']}"}


async def new_workspace(client: httpx.AsyncClient) -> tuple[str, dict[str, str], str]:
    """A fresh workspace with one admin and an open collection, isolated from other tests."""
    _, headers = await register(client, "admin")
    workspace = (await client.post("/api/v1/workspaces", json={"name": "Test"}, headers=headers)).json()
    collection = (
        await client.post(
            f"/api/v1/workspaces/{workspace['id']}/collections",
            json={"name": "Docs", "visibility": "workspace", "group_ids": []},
            headers=headers,
        )
    ).json()
    return workspace["id"], headers, collection["id"]


async def ingest_all(app: Any) -> int:
    """Run the background worker until the job queue is empty."""
    return await drain(app.state.sessionmaker, app.state.providers, app.state.settings)


def parse_sse(body: str) -> list[tuple[str, Any]]:
    """Parse a Server-Sent Events body into (event, decoded JSON data) pairs."""
    import json

    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events
