"""Annotations are private to their author and only possible on documents the author can read (404 otherwise)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select

from app.models.annotations import Annotation
from tests.conftest import ingest_all, new_workspace, register

API = "/api/v1"
FIXTURES = Path(__file__).parent.parent / "fixtures"
RECT = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.02}


def body(**overrides: Any) -> dict[str, Any]:
    return {"page": 1, "rects": [RECT], "text": "a selected sentence", "note": "check this", "color": "green", **overrides}


async def upload_pdf(client: httpx.AsyncClient, headers: dict[str, str], collection_id: str) -> str:
    response = await client.post(
        f"{API}/collections/{collection_id}/documents",
        files={"file": ("sample.pdf", (FIXTURES / "sample.pdf").read_bytes(), "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


async def add_member(client: httpx.AsyncClient, admin: dict[str, str], workspace_id: str, email: str) -> None:
    response = await client.post(
        f"{API}/workspaces/{workspace_id}/members", json={"email": email, "role": "member"}, headers=admin
    )
    assert response.status_code == 201, response.text


async def test_create_list_update_delete_roundtrip(client: httpx.AsyncClient, app: Any) -> None:
    _, admin, collection_id = await new_workspace(client)
    doc = await upload_pdf(client, admin, collection_id)
    await ingest_all(app)

    created = await client.post(f"{API}/documents/{doc}/annotations", json=body(), headers=admin)
    assert created.status_code == 201, created.text
    annotation = created.json()
    assert annotation["color"] == "green" and annotation["note"] == "check this" and annotation["rects"] == [RECT]

    listed = (await client.get(f"{API}/documents/{doc}/annotations", headers=admin)).json()
    assert [a["id"] for a in listed] == [annotation["id"]]

    patched = await client.patch(
        f"{API}/annotations/{annotation['id']}", json={"note": "revised", "color": "pink"}, headers=admin
    )
    assert patched.status_code == 200
    assert patched.json()["note"] == "revised" and patched.json()["color"] == "pink"
    assert patched.json()["text"] == "a selected sentence"  # only note and colour are editable

    assert (await client.delete(f"{API}/annotations/{annotation['id']}", headers=admin)).status_code == 204
    assert (await client.get(f"{API}/documents/{doc}/annotations", headers=admin)).json() == []
    assert (await client.delete(f"{API}/annotations/{annotation['id']}", headers=admin)).status_code == 404


async def test_annotations_are_private_to_their_author(client: httpx.AsyncClient, app: Any) -> None:
    workspace_id, admin, collection_id = await new_workspace(client)
    doc = await upload_pdf(client, admin, collection_id)
    await ingest_all(app)
    colleague_email, colleague = await register(client, "colleague")
    await add_member(client, admin, workspace_id, colleague_email)  # can read the open collection, like the admin

    mine = (await client.post(f"{API}/documents/{doc}/annotations", json=body(note="private thought"), headers=admin)).json()

    # the colleague reads the same document but sees none of the admin's highlights
    assert (await client.get(f"{API}/documents/{doc}/annotations", headers=colleague)).json() == []
    # and cannot change or delete them: the row looks like it does not exist
    assert (await client.patch(f"{API}/annotations/{mine['id']}", json={"note": "x"}, headers=colleague)).status_code == 404
    assert (await client.delete(f"{API}/annotations/{mine['id']}", headers=colleague)).status_code == 404

    theirs = (
        await client.post(f"{API}/documents/{doc}/annotations", json=body(note="their note"), headers=colleague)
    ).json()
    assert "private thought" not in str((await client.get(f"{API}/documents/{doc}/annotations", headers=colleague)).json())
    assert "their note" not in str((await client.get(f"{API}/documents/{doc}/annotations", headers=admin)).json())
    assert (await client.patch(f"{API}/annotations/{theirs['id']}", json={"note": "x"}, headers=admin)).status_code == 404

    # still intact for the author
    assert (await client.get(f"{API}/documents/{doc}/annotations", headers=admin)).json()[0]["note"] == "private thought"


async def test_a_document_the_caller_cannot_read_looks_nonexistent(client: httpx.AsyncClient, app: Any) -> None:
    workspace_id, admin, _ = await new_workspace(client)
    group = (await client.post(f"{API}/workspaces/{workspace_id}/groups", json={"name": "chosen-few"}, headers=admin)).json()
    restricted = (
        await client.post(
            f"{API}/workspaces/{workspace_id}/collections",
            json={"name": "Restricted", "visibility": "groups", "group_ids": [group["id"]]},
            headers=admin,
        )
    ).json()
    doc = await upload_pdf(client, admin, restricted["id"])
    await ingest_all(app)
    member_email, member = await register(client, "member")
    await add_member(client, admin, workspace_id, member_email)
    _, outsider = await register(client, "outsider")  # not in the workspace at all

    mine = (await client.post(f"{API}/documents/{doc}/annotations", json=body(), headers=admin)).json()
    for who in (member, outsider):
        assert (await client.get(f"{API}/documents/{doc}/annotations", headers=who)).status_code == 404
        assert (await client.post(f"{API}/documents/{doc}/annotations", json=body(), headers=who)).status_code == 404
        assert (await client.patch(f"{API}/annotations/{mine['id']}", json={"note": "x"}, headers=who)).status_code == 404
        assert (await client.delete(f"{API}/annotations/{mine['id']}", headers=who)).status_code == 404
    # the same answer for a document that does not exist, so existence is not revealed
    missing = "00000000-0000-4000-8000-000000000000"
    assert (await client.get(f"{API}/documents/{missing}/annotations", headers=member)).status_code == 404


async def test_losing_access_hides_your_own_highlights(client: httpx.AsyncClient, app: Any) -> None:
    workspace_id, admin, collection_id = await new_workspace(client)
    doc = await upload_pdf(client, admin, collection_id)
    await ingest_all(app)
    member_email, member = await register(client, "member")
    await add_member(client, admin, workspace_id, member_email)
    created = (await client.post(f"{API}/documents/{doc}/annotations", json=body(), headers=member)).json()

    # the admin narrows the collection to a group the member is not in
    group = (await client.post(f"{API}/workspaces/{workspace_id}/groups", json={"name": "only"}, headers=admin)).json()
    narrowed = await client.patch(
        f"{API}/collections/{collection_id}", json={"visibility": "groups", "group_ids": [group["id"]]}, headers=admin
    )
    assert narrowed.status_code == 200, narrowed.text
    assert (await client.get(f"{API}/documents/{doc}/annotations", headers=member)).status_code == 404
    assert (await client.patch(f"{API}/annotations/{created['id']}", json={"note": "x"}, headers=member)).status_code == 404


async def test_validation(client: httpx.AsyncClient, app: Any) -> None:
    _, admin, collection_id = await new_workspace(client)
    doc = await upload_pdf(client, admin, collection_id)
    await ingest_all(app)
    url = f"{API}/documents/{doc}/annotations"
    pages = (await client.get(f"{API}/documents/{doc}", headers=admin)).json()["page_count"]
    assert pages == 2

    assert (await client.post(url, json=body(page=pages + 1), headers=admin)).status_code == 422
    assert (await client.post(url, json=body(page=0), headers=admin)).status_code == 422
    assert (await client.post(url, json=body(rects=[]), headers=admin)).status_code == 422
    assert (
        await client.post(url, json=body(rects=[{"x": 0.9, "y": 0.1, "w": 0.5, "h": 0.1}]), headers=admin)
    ).status_code == 422
    assert (
        await client.post(url, json=body(rects=[{"x": -0.1, "y": 0.1, "w": 0.1, "h": 0.1}]), headers=admin)
    ).status_code == 422
    assert (await client.post(url, json=body(text=""), headers=admin)).status_code == 422
    assert (await client.post(url, json=body(text="x" * 2001), headers=admin)).status_code == 422
    assert (await client.post(url, json=body(color="red"), headers=admin)).status_code == 422
    assert (await client.post(url, json=body(rects=[RECT] * 101), headers=admin)).status_code == 422
    defaults = await client.post(url, json={"page": 2, "rects": [RECT], "text": "plain"}, headers=admin)
    assert defaults.status_code == 201 and defaults.json()["color"] == "yellow" and defaults.json()["note"] == ""
    assert (await client.post(url, json=body(), headers={})).status_code == 401


async def test_only_pdfs_can_be_highlighted(client: httpx.AsyncClient) -> None:
    _, admin, collection_id = await new_workspace(client)
    created = await client.post(
        f"{API}/collections/{collection_id}/documents",
        files={"file": ("notes.md", b"# Notes\n\nSome plain markdown text.", "text/markdown")},
        headers=admin,
    )
    response = await client.post(f"{API}/documents/{created.json()['id']}/annotations", json=body(), headers=admin)
    assert response.status_code == 422


async def test_deleting_the_document_deletes_its_annotations(client: httpx.AsyncClient, app: Any) -> None:
    _, admin, collection_id = await new_workspace(client)
    doc = await upload_pdf(client, admin, collection_id)
    await ingest_all(app)
    await client.post(f"{API}/documents/{doc}/annotations", json=body(), headers=admin)

    async def count() -> int:
        async with app.state.sessionmaker() as session:
            return int((await session.execute(select(func.count()).select_from(Annotation))).scalar_one())

    before = await count()
    assert (await client.delete(f"{API}/documents/{doc}", headers=admin)).status_code == 204
    assert await count() == before - 1
