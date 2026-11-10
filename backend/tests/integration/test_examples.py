"""The sample company end to end: app.seed_example creates the workspace, the watched-folder inbox imports
examples/inbox, and each login sees exactly the collections its groups allow."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.seed_example import COLLECTIONS, DOMAIN, seed_example
from app.worker import inbox_watcher
from app.worker.runner import drain
from tests.conftest import PASSWORD, login, make_providers, make_settings, running_app

API = "/api/v1"
EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "inbox"
SAMPLE_FILES = sorted(p for p in EXAMPLES.rglob("*") if p.is_file())
VISIBLE = {  # login -> the collections it may read
    "admin": set(COLLECTIONS),
    "employee": {"Handbook"},
    "engineer": {"Handbook", "Engineering"},
    "finance": {"Handbook", "Finance-Confidential"},
}


@pytest.fixture
async def company(
    pg_url: str, storage_dir: str, tmp_path: Path
) -> AsyncIterator[tuple[Any, httpx.AsyncClient, dict[str, str]]]:
    root = tmp_path / "inbox"
    shutil.copytree(EXAMPLES, root)  # a copy: a writable scan moves files, and the tracked samples must stay put
    settings = make_settings(pg_url, storage_dir, inbox_root=str(root), inbox_settle_seconds=0)
    async with running_app(settings, make_providers(storage_dir)) as app:
        result = await seed_example(app.state.sessionmaker, app.state.providers, settings, password=PASSWORD)
        summary = await inbox_watcher.scan_once(app.state.sessionmaker, app.state.providers, settings)
        # The test database is shared: a later test finds the files already handled, which must not import them twice.
        assert summary.imported + summary.skipped + summary.duplicate == len(SAMPLE_FILES), summary.counts()
        assert summary.quarantined == summary.failed == 0
        await drain(app.state.sessionmaker, app.state.providers, settings)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield app, client, {name: str(cid) for name, cid in result.collections.items()}


async def test_each_login_sees_exactly_its_collections(company: tuple[Any, httpx.AsyncClient, dict[str, str]]) -> None:
    _, client, collections = company
    expected = {name: sorted(p.name for p in SAMPLE_FILES if p.parent.name == name) for name in COLLECTIONS}
    for user, visible in VISIBLE.items():
        headers = await login(client, f"{user}@{DOMAIN}")
        for name, collection_id in collections.items():
            response = await client.get(f"{API}/collections/{collection_id}/documents", headers=headers)
            if name in visible:
                docs = response.json()
                assert sorted(d["filename"] for d in docs) == expected[name], (user, name)
                assert {d["status"] for d in docs} == {"ready"}, (user, name)
            else:
                assert response.status_code == 404, f"{user} must not see {name}"


async def test_answers_never_cite_a_collection_the_asker_cannot_read(
    company: tuple[Any, httpx.AsyncClient, dict[str, str]],
) -> None:
    _, client, _ = company
    admin = await login(client, f"admin@{DOMAIN}")
    workspace_id = next(
        w["id"]
        for w in (await client.get(f"{API}/workspaces", headers=admin)).json()
        if w["name"] == "Fernhollow Bicycle Works"
    )
    finance_titles = {
        "Q3 2026 Financial Results: Board Pack Summary",
        "Salary Bands 2026",
        "Vendor Contract Summary: Ardent Tube Co.",
    }

    finance = await login(client, f"finance@{DOMAIN}")
    answer = (
        await client.post(
            f"{API}/ask", json={"workspace_id": workspace_id, "question": "What was revenue in Q3 2026?"}, headers=finance
        )
    ).json()
    assert answer["status"] == "answered"
    assert any(c["document_title"] in finance_titles for claim in answer["claims"] for c in claim["citations"])

    employee = await login(client, f"employee@{DOMAIN}")
    answer = (
        await client.post(
            f"{API}/ask", json={"workspace_id": workspace_id, "question": "What was revenue in Q3 2026?"}, headers=employee
        )
    ).json()
    cited = {c["document_title"] for claim in answer["claims"] for c in claim["citations"]}
    assert not cited & finance_titles, "an employee must never get a citation from Finance-Confidential"
