"""The viewer and learning routes leave audit entries, and the entries carry ids and counts but no user text."""

from __future__ import annotations

from typing import Any

import httpx

from tests.integration.learning_helpers import make_lab
from tests.integration.test_annotations import body, upload_pdf

API = "/api/v1"
NOTE = "tiger-lily-private-note"


async def actions(client: httpx.AsyncClient, lab_admin: dict[str, str], workspace_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"{API}/workspaces/{workspace_id}/audit-events", params={"limit": 200}, headers=lab_admin)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def test_annotation_and_learning_actions_are_audited_without_their_text(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    pdf = await upload_pdf(client, lab.admin, lab.collection_id)
    from tests.conftest import ingest_all

    await ingest_all(app)

    created = await client.post(f"{API}/documents/{pdf}/annotations", json=body(note=NOTE), headers=lab.admin)
    assert created.status_code == 201, created.text
    assert (await client.delete(f"{API}/annotations/{created.json()['id']}", headers=lab.admin)).status_code == 204

    plan = await client.post(
        f"{API}/workspaces/{lab.workspace_id}/learning-plans",
        json={"document_ids": [lab.doc("vacation.md")], "title": "Vacation"},
        headers=lab.admin,
    )
    assert plan.status_code == 201, plan.text
    assert (await client.delete(f"{API}/learning-plans/{plan.json()['id']}", headers=lab.admin)).status_code == 204

    summary = await client.post(
        f"{API}/workspaces/{lab.workspace_id}/learning/summarize",
        json={"document_id": lab.doc("vacation.md")},
        headers=lab.admin,
    )
    assert summary.status_code == 200, summary.text

    entries = await actions(client, lab.admin, lab.workspace_id)
    seen = {entry["action"] for entry in entries}
    assert {
        "annotation.create",
        "annotation.delete",
        "learning.plan_create",
        "learning.plan_delete",
        "learning.summarize",
    } <= seen
    assert NOTE not in str(entries)  # the note is the author's private text: ids and counts only
