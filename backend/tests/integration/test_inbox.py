"""Watched-folder ingestion: the folder decides the collection (and so the audience); anything doubtful is quarantined."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pymupdf
import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.models.annotations import InboxItem
from app.worker import inbox_watcher
from app.worker.runner import drain
from tests.conftest import make_providers, make_settings, register, running_app

API = "/api/v1"


def pdf_bytes(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    data: bytes = doc.tobytes()
    doc.close()
    return data


@dataclass
class Inbox:
    app: Any
    client: httpx.AsyncClient
    root: Path

    async def scan(self) -> inbox_watcher.ScanSummary:
        return await inbox_watcher.scan_once(self.app.state.sessionmaker, self.app.state.providers, self.app.state.settings)

    async def ingest(self) -> int:
        return await drain(self.app.state.sessionmaker, self.app.state.providers, self.app.state.settings)

    def drop(self, *parts: str, data: bytes) -> Path:
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path


@pytest.fixture
async def inbox(pg_url: str, storage_dir: str, tmp_path: Path) -> AsyncIterator[Inbox]:
    root = tmp_path / "inbox"
    root.mkdir()
    settings = make_settings(pg_url, storage_dir, inbox_root=str(root), inbox_settle_seconds=0)
    async with running_app(settings, make_providers(storage_dir)) as app:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield Inbox(app, client, root)


@dataclass
class Space:
    workspace_id: str
    folder: str  # first folder level
    admin: dict[str, str]


async def new_space(inbox: Inbox, collections: tuple[tuple[str, str], ...] = (("Policies", "workspace"),)) -> Space:
    c = inbox.client
    _, admin = await register(c, "admin")
    name = f"Inbox {uuid.uuid4().hex[:8]}"
    workspace = (await c.post(f"{API}/workspaces", json={"name": name}, headers=admin)).json()
    group = (await c.post(f"{API}/workspaces/{workspace['id']}/groups", json={"name": "chosen-few"}, headers=admin)).json()
    for cname, visibility in collections:
        made = await c.post(
            f"{API}/workspaces/{workspace['id']}/collections",
            json={"name": cname, "visibility": visibility, "group_ids": [group["id"]] if visibility == "groups" else []},
            headers=admin,
        )
        assert made.status_code == 201, made.text
    status = (await c.get(f"{API}/workspaces/{workspace['id']}/inbox", headers=admin)).json()
    return Space(workspace["id"], status["workspace_folder"], admin)


async def items(inbox: Inbox, space: Space, **params: str) -> list[dict[str, Any]]:
    response = await inbox.client.get(
        f"{API}/workspaces/{space.workspace_id}/inbox/items", params=params, headers=space.admin
    )
    assert response.status_code == 200, response.text
    return list(response.json())


async def collection_id(inbox: Inbox, space: Space, name: str) -> str:
    listed = (await inbox.client.get(f"{API}/workspaces/{space.workspace_id}/collections", headers=space.admin)).json()
    return str(next(c["id"] for c in listed if c["name"] == name))


async def test_a_dropped_pdf_is_imported_into_the_folder_collection_and_ingested(inbox: Inbox) -> None:
    space = await new_space(inbox)
    assert space.folder.startswith("inbox-")
    src = inbox.drop(space.folder, "Policies", "leave.pdf", data=pdf_bytes(f"Parental leave is 16 weeks. {uuid.uuid4()}"))

    summary = await inbox.scan()
    assert summary.imported == 1 and summary.quarantined == 0
    assert not src.exists()
    assert (inbox.root / ".processed" / space.folder / "Policies" / "leave.pdf").exists()

    assert await inbox.ingest() >= 1
    (item,) = await items(inbox, space)
    assert item["status"] == "imported" and item["collection_name"] == "Policies" and item["document_status"] == "ready"
    docs = (
        await inbox.client.get(
            f"{API}/collections/{await collection_id(inbox, space, 'Policies')}/documents", headers=space.admin
        )
    ).json()
    assert [d["id"] for d in docs] == [item["document_id"]]
    assert docs[0]["mime"] == "application/pdf" and docs[0]["status"] == "ready" and docs[0]["page_count"] == 1
    assert (await inbox.client.get(f"{API}/documents/{docs[0]['id']}/file", headers=space.admin)).content.startswith(b"%PDF")

    status = (await inbox.client.get(f"{API}/workspaces/{space.workspace_id}/inbox", headers=space.admin)).json()
    assert status["enabled"] is True and status["last_scan_at"] is not None and status["scan_requested"] is False
    folder = next(f for f in status["folders"] if f["collection_name"] == "Policies")
    assert folder["folder"] == f"{space.folder}/Policies" and folder["imported"] == 1 and folder["matched"] is True


async def test_the_collection_folder_sets_the_audience_never_a_broader_one(inbox: Inbox) -> None:
    space = await new_space(inbox, (("Open", "workspace"), ("Secret", "groups")))
    member_email, member = await register(inbox.client, "member")
    added = await inbox.client.post(
        f"{API}/workspaces/{space.workspace_id}/members", json={"email": member_email, "role": "member"}, headers=space.admin
    )
    assert added.status_code == 201
    inbox.drop(space.folder, "Secret", "salaries.md", data=f"# Salaries\n\nBands are confidential. {uuid.uuid4()}".encode())
    inbox.drop(space.folder, "Open", "lunch.md", data=f"# Lunch\n\nSoup on Fridays. {uuid.uuid4()}".encode())
    assert (await inbox.scan()).imported == 2
    await inbox.ingest()

    secret = await collection_id(inbox, space, "Secret")
    assert (await inbox.client.get(f"{API}/collections/{secret}/documents", headers=member)).status_code == 404
    admin_docs = (await inbox.client.get(f"{API}/collections/{secret}/documents", headers=space.admin)).json()
    assert [d["filename"] for d in admin_docs] == ["salaries.md"]
    document_id = admin_docs[0]["id"]
    for suffix in ("", "/file", "/chunks"):
        assert (await inbox.client.get(f"{API}/documents/{document_id}{suffix}", headers=member)).status_code == 404
    open_docs = (
        await inbox.client.get(f"{API}/collections/{await collection_id(inbox, space, 'Open')}/documents", headers=member)
    ).json()
    assert [d["filename"] for d in open_docs] == ["lunch.md"]


async def test_an_unknown_collection_folder_is_quarantined_not_imported(inbox: Inbox) -> None:
    space = await new_space(inbox)
    data = f"# Oops\n\nA file in a folder that is no collection. {uuid.uuid4()}".encode()
    inbox.drop(space.folder, "Polcies", "typo.md", data=data)  # a typo in the collection name

    summary = await inbox.scan()
    assert summary.quarantined == 1 and summary.imported == 0
    assert (inbox.root / ".quarantine" / space.folder / "Polcies" / "typo.md").read_bytes() == data

    (item,) = await items(inbox, space, status="quarantined")
    assert item["document_id"] is None and item["collection_id"] is None
    assert "no collection" in item["reason"].lower()
    status = (await inbox.client.get(f"{API}/workspaces/{space.workspace_id}/inbox", headers=space.admin)).json()
    unmatched = [f for f in status["folders"] if not f["matched"]]
    assert [(f["folder"], f["quarantined"]) for f in unmatched] == [(f"{space.folder}/Polcies", 1)]
    # nothing was created for it
    assert [
        d
        for c in ("Policies",)
        for d in (
            await inbox.client.get(
                f"{API}/collections/{await collection_id(inbox, space, c)}/documents", headers=space.admin
            )
        ).json()
    ] == []


async def test_files_outside_any_workspace_or_collection_folder_are_quarantined(inbox: Inbox) -> None:
    space = await new_space(inbox)
    inbox.drop("loose.md", data=f"# Loose\n\nAt the root. {uuid.uuid4()}".encode())
    inbox.drop("no-such-workspace", "Policies", "a.md", data=f"# A\n\nNobody's folder. {uuid.uuid4()}".encode())
    inbox.drop(space.folder, "directly-in-workspace.md", data=f"# B\n\nNo collection folder. {uuid.uuid4()}".encode())
    inbox.drop(space.folder, "Policies", "deeper", "c.md", data=f"# C\n\nToo deep. {uuid.uuid4()}".encode())

    summary = await inbox.scan()
    assert summary.quarantined == 4 and summary.imported == 0
    # only the two that belong to this workspace's folder are shown to its admin; the other two have no owner to show them to
    reasons = sorted(i["filename"] for i in await items(inbox, space, status="quarantined"))
    assert reasons == ["c.md", "directly-in-workspace.md"]


async def test_another_workspaces_admin_never_sees_these_items(inbox: Inbox) -> None:
    mine, theirs = await new_space(inbox), await new_space(inbox)
    inbox.drop(mine.folder, "Nope", "x.md", data=f"# X\n\nMine. {uuid.uuid4()}".encode())
    await inbox.scan()
    assert len(await items(inbox, mine)) == 1
    assert await items(inbox, theirs) == []
    # and cannot read my workspace's inbox at all
    response = await inbox.client.get(f"{API}/workspaces/{mine.workspace_id}/inbox/items", headers=theirs.admin)
    assert response.status_code == 404


async def test_duplicates_are_detected_by_content(inbox: Inbox) -> None:
    space = await new_space(inbox)
    data = f"# Same\n\nIdentical content. {uuid.uuid4()}".encode()
    inbox.drop(space.folder, "Policies", "one.md", data=data)
    assert (await inbox.scan()).imported == 1
    inbox.drop(space.folder, "Policies", "copy-of-one.md", data=data)
    summary = await inbox.scan()
    assert summary.duplicate == 1 and summary.imported == 0
    assert sorted(i["status"] for i in await items(inbox, space)) == ["duplicate", "imported"]


async def test_content_decides_the_type_not_the_name(inbox: Inbox) -> None:
    space = await new_space(inbox)
    inbox.drop(space.folder, "Policies", "fake.pdf", data=b"MZ\x90\x00\x03\x00\x00\x00 an executable pretending")
    inbox.drop(space.folder, "Policies", "text-as-pdf.pdf", data=f"# Just markdown {uuid.uuid4()}".encode())
    inbox.drop(space.folder, "Policies", "tool.exe", data=b"MZ\x90\x00")
    inbox.drop(space.folder, "Policies", "empty.md", data=b"")
    summary = await inbox.scan()
    assert summary.failed == 4 and summary.imported == 0
    reasons = {i["filename"]: i["reason"] for i in await items(inbox, space, status="failed")}
    assert set(reasons) == {"fake.pdf", "text-as-pdf.pdf", "tool.exe", "empty.md"}
    assert "does not match" in reasons["text-as-pdf.pdf"]
    assert (inbox.root / ".failed" / space.folder / "Policies" / "fake.pdf").exists()


async def test_oversized_files_are_refused_without_being_read(inbox: Inbox) -> None:
    space = await new_space(inbox)
    inbox.app.state.settings.inbox_max_file_mb = 1
    inbox.drop(space.folder, "Policies", "big.md", data=b"# Big\n\n" + b"word " * 300_000)
    summary = await inbox.scan()
    assert summary.failed == 1
    (item,) = await items(inbox, space, status="failed")
    assert "larger than 1 MB" in item["reason"] and item["document_id"] is None


async def test_files_still_being_written_are_left_alone(inbox: Inbox) -> None:
    space = await new_space(inbox)
    inbox.app.state.settings.inbox_settle_seconds = 3600
    src = inbox.drop(space.folder, "Policies", "fresh.md", data=f"# Fresh\n\nJust copied. {uuid.uuid4()}".encode())
    summary = await inbox.scan()
    assert summary.waiting == 1 and summary.imported == 0 and src.exists()
    assert await items(inbox, space) == []  # nothing recorded yet
    inbox.app.state.settings.inbox_settle_seconds = 0
    assert (await inbox.scan()).imported == 1


async def test_a_file_that_cannot_be_moved_is_still_imported_only_once(
    inbox: Inbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    space = await new_space(inbox)
    monkeypatch.setattr(inbox_watcher, "archive", lambda *a, **k: False)  # e.g. a read-only mount
    src = inbox.drop(space.folder, "Policies", "stays.md", data=f"# Stays\n\nNot movable. {uuid.uuid4()}".encode())
    assert (await inbox.scan()).imported == 1
    again = await inbox.scan()
    assert again.imported == 0 and again.duplicate == 0 and again.skipped == 1 and src.exists()
    assert len(await items(inbox, space)) == 1


async def test_symlinks_are_never_followed(inbox: Inbox, tmp_path: Path) -> None:
    space = await new_space(inbox)
    secret = tmp_path / "secret.md"
    secret.write_text(f"# Secret\n\nOutside the inbox. {uuid.uuid4()}")
    link = inbox.root / space.folder / "Policies" / "innocent.md"
    link.parent.mkdir(parents=True)
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available (Windows without developer mode)")
    summary = await inbox.scan()
    assert summary.quarantined == 1 and summary.imported == 0
    assert link.is_symlink() and secret.exists()  # not read, not moved, not deleted
    (item,) = await items(inbox, space)
    assert item["status"] == "quarantined" and "symbolic" in item["reason"].lower() and item["document_id"] is None


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS junctions")
async def test_a_junction_that_leaves_the_inbox_is_not_read(inbox: Inbox, tmp_path: Path) -> None:
    space = await new_space(inbox)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text(f"# Secret\n\nOutside the inbox. {uuid.uuid4()}")
    (inbox.root / space.folder).mkdir(parents=True)
    made = subprocess.run(  # noqa: ASYNC221, S603  (a test-only helper with fixed arguments)
        ["cmd", "/c", "mklink", "/J", str(inbox.root / space.folder / "Policies"), str(outside)],  # noqa: S607
        capture_output=True,
        check=False,
    )
    if made.returncode != 0:
        pytest.skip("could not create a junction")
    summary = await inbox.scan()
    assert summary.imported == 0 and summary.quarantined == 1
    assert (outside / "secret.md").exists()  # not read through the junction, not moved
    (item,) = await items(inbox, space, status="quarantined")
    assert "outside" in item["reason"].lower() and item["document_id"] is None


async def test_scan_request_and_admin_only(inbox: Inbox) -> None:
    space = await new_space(inbox)
    member_email, member = await register(inbox.client, "member")
    await inbox.client.post(
        f"{API}/workspaces/{space.workspace_id}/members", json={"email": member_email, "role": "member"}, headers=space.admin
    )
    _, outsider = await register(inbox.client, "outsider")
    base = f"{API}/workspaces/{space.workspace_id}/inbox"
    for path in ("", "/items"):
        assert (await inbox.client.get(base + path, headers=member)).status_code == 403
        assert (await inbox.client.get(base + path, headers=outsider)).status_code == 404
        assert (await inbox.client.get(base + path)).status_code == 401
    assert (await inbox.client.post(base + "/scan", headers=member)).status_code == 403
    assert (await inbox.client.post(base + "/scan", headers=outsider)).status_code == 404

    requested = await inbox.client.post(base + "/scan", headers=space.admin)
    assert requested.status_code == 202 and requested.json()["scan_requested"] is True
    await inbox.scan()
    status = (await inbox.client.get(base, headers=space.admin)).json()
    assert status["scan_requested"] is False and status["last_scan_at"] is not None


async def test_the_feature_is_off_without_an_inbox_root(client: httpx.AsyncClient, world: Any) -> None:
    base = f"{API}/workspaces/{world.workspace_id}/inbox"
    status = (await client.get(base, headers=world.admin)).json()
    assert status["enabled"] is False
    assert (await client.post(base + "/scan", headers=world.admin)).status_code == 409
    summary = await inbox_watcher.scan_once(None, None, Settings(inbox_root=""))  # type: ignore[arg-type]
    assert summary.problem is not None  # nothing is touched, not even the database


async def test_two_scanners_do_not_overlap(inbox: Inbox) -> None:
    space = await new_space(inbox)
    inbox.drop(space.folder, "Policies", "once.md", data=f"# Once\n\nOnly one scanner imports. {uuid.uuid4()}".encode())
    first, second = await asyncio.gather(inbox.scan(), inbox.scan())
    assert first.imported + second.imported == 1
    async with inbox.app.state.sessionmaker() as session:
        total = (
            await session.execute(
                select(func.count()).select_from(InboxItem).where(InboxItem.workspace_id == uuid.UUID(space.workspace_id))
            )
        ).scalar_one()
    assert total == 1
