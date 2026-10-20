"""ACL leak tests (mandatory for every endpoint that returns content, chunks, files, citations or diagnostics).

The seeded workspace has a `General` collection (everyone) and `People-Ops-Confidential` (group `hr` only).
`employee@` is a plain member, `hr@` is in the hr group, `admin@` is the workspace admin."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.conftest import World, ingest_all, new_workspace, parse_sse, register

API = "/api/v1"
CONFIDENTIAL_MARKERS = ("salary", "severance", "performance improvement", "investigation", "bonus", "l5")


async def confidential_ids(client: httpx.AsyncClient, world: World) -> tuple[list[str], list[str]]:
    docs = (await client.get(f"{API}/collections/{world.confidential_id}/documents", headers=world.admin)).json()
    assert docs, "seed must create confidential documents"
    doc_ids = [d["id"] for d in docs]
    chunk_ids: list[str] = []
    for doc_id in doc_ids:
        chunks = (await client.get(f"{API}/documents/{doc_id}/chunks", headers=world.admin)).json()
        chunk_ids += [c["id"] for c in chunks]
    return doc_ids, chunk_ids


def all_text(payload: Any) -> str:
    return str(payload).lower()


# --- listing ------------------------------------------------------------------------------------
async def test_collection_list_hides_restricted_collections(client: httpx.AsyncClient, world: World) -> None:
    employee = (await client.get(f"{API}/workspaces/{world.workspace_id}/collections", headers=world.employee)).json()
    hr = (await client.get(f"{API}/workspaces/{world.workspace_id}/collections", headers=world.hr)).json()
    admin = (await client.get(f"{API}/workspaces/{world.workspace_id}/collections", headers=world.admin)).json()
    assert [c["name"] for c in employee] == ["General"]
    assert {c["name"] for c in hr} == {"General", "People-Ops-Confidential"}
    assert {c["name"] for c in admin} == {"General", "People-Ops-Confidential"}


async def test_restricted_collection_looks_nonexistent_to_outsiders(client: httpx.AsyncClient, world: World) -> None:
    response = await client.get(f"{API}/collections/{world.confidential_id}/documents", headers=world.employee)
    assert response.status_code == 404  # 404, not 403: existence is not revealed
    assert (await client.get(f"{API}/collections/{world.confidential_id}/documents", headers=world.hr)).status_code == 200


# --- every content endpoint, as the employee --------------------------------------------------
async def test_employee_cannot_read_restricted_documents_chunks_or_files(client: httpx.AsyncClient, world: World) -> None:
    doc_ids, chunk_ids = await confidential_ids(client, world)
    for doc_id in doc_ids:
        for suffix in ("", "/file", "/chunks"):
            response = await client.get(f"{API}/documents/{doc_id}{suffix}", headers=world.employee)
            assert response.status_code == 404, f"GET /documents/{{id}}{suffix} leaked to a plain member"
    for chunk_id in chunk_ids:
        assert (await client.get(f"{API}/chunks/{chunk_id}", headers=world.employee)).status_code == 404


async def test_hr_can_read_what_the_employee_cannot(client: httpx.AsyncClient, world: World) -> None:
    doc_ids, chunk_ids = await confidential_ids(client, world)
    assert (await client.get(f"{API}/documents/{doc_ids[0]}", headers=world.hr)).status_code == 200
    assert (await client.get(f"{API}/documents/{doc_ids[0]}/file", headers=world.hr)).status_code == 200
    assert (await client.get(f"{API}/chunks/{chunk_ids[0]}", headers=world.hr)).status_code == 200


async def test_employee_cannot_modify_anything(client: httpx.AsyncClient, world: World) -> None:
    doc_ids, _ = await confidential_ids(client, world)
    assert (await client.delete(f"{API}/documents/{doc_ids[0]}", headers=world.employee)).status_code == 404
    assert (await client.post(f"{API}/documents/{doc_ids[0]}/reindex", headers=world.employee)).status_code == 404
    general_docs = (await client.get(f"{API}/collections/{world.general_id}/documents", headers=world.employee)).json()
    assert (await client.delete(f"{API}/documents/{general_docs[0]['id']}", headers=world.employee)).status_code == 403
    upload = await client.post(
        f"{API}/collections/{world.general_id}/documents",
        files={"file": ("x.md", b"# x\ntext here.", "text/markdown")},
        headers=world.employee,
    )
    assert upload.status_code == 403
    patch = await client.patch(
        f"{API}/collections/{world.confidential_id}", json={"visibility": "workspace"}, headers=world.employee
    )
    assert patch.status_code == 404


# --- ask -----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "question",
    [
        "What is the base salary range for level L5?",
        "What is the maximum severance in weeks?",
        "How many days does a performance improvement plan run before the final decision?",
        "Who handles workplace investigations that involve an executive?",
    ],
)
async def test_restricted_questions_are_refused_for_employees_and_never_leak(
    client: httpx.AsyncClient, world: World, question: str
) -> None:
    response = await client.post(
        f"{API}/ask", json={"workspace_id": world.workspace_id, "question": question}, headers=world.employee
    )
    assert response.status_code == 200
    answer = response.json()
    assert answer["status"] == "refused"
    assert answer["claims"] == []
    body = all_text(answer)
    for forbidden in ("150,000", "190,000", "26 weeks", "60 days", "external counsel"):
        assert forbidden not in body
    titles = {s["document_title"] for s in answer["refusal"]["closest_sources"]}
    assert not titles & {"Salary Bands (Confidential)", "Severance And Layoffs", "Performance Improvement Plan"}


async def test_the_same_questions_are_answered_for_hr_with_confidential_citations(
    client: httpx.AsyncClient, world: World
) -> None:
    response = await client.post(
        f"{API}/ask",
        json={"workspace_id": world.workspace_id, "question": "What is the annual bonus target for level L5?"},
        headers=world.hr,
    )
    answer = response.json()
    assert answer["status"] == "answered"
    # What matters here is access: HR gets an answer cited to the confidential document the employee cannot open.
    assert answer["claims"][0]["citations"][0]["document_title"].lower().startswith("salary")


async def test_streaming_endpoint_is_also_filtered(client: httpx.AsyncClient, world: World) -> None:
    response = await client.post(
        f"{API}/ask/stream",
        json={"workspace_id": world.workspace_id, "question": "What is the maximum severance in weeks?"},
        headers=world.employee,
    )
    assert response.status_code == 200
    events = parse_sse(response.text)
    final = events[-1][1]
    assert events[-1][0] == "final" and final["status"] == "refused"
    assert "26 weeks" not in response.text and "maximum is 26" not in response.text
    assert [e for e, _ in events if e == "token"], "a refusal is still streamed as text"


async def test_retrieval_explain_shows_each_caller_only_what_their_acl_allows(
    client: httpx.AsyncClient, world: World
) -> None:
    params = {"workspace_id": world.workspace_id, "query": "salary range level severance bonus"}

    def titles(trace: dict[str, Any]) -> set[str]:
        stages = trace["vector"] + trace["fts"] + trace["fused"] + trace["reranked"]
        return {c["document_title"] for c in stages}

    employee = (await client.get(f"{API}/retrieval/explain", params=params, headers=world.employee)).json()
    assert employee["allowed_collections"] == 1
    assert employee["vector"], "the employee still gets a useful trace over the General collection"
    assert not any(
        marker in all_text(employee) for marker in ("salary bands", "severance and layoff", "performance improvement")
    )
    assert not {t for t in titles(employee) if "confidential" in t.lower()}

    for headers in (world.hr, world.admin):
        trace = (await client.get(f"{API}/retrieval/explain", params=params, headers=headers)).json()
        assert trace["allowed_collections"] == 2
        assert any("Salary" in t for t in titles(trace))


async def test_retrieval_explain_is_invisible_to_outsiders(client: httpx.AsyncClient, world: World) -> None:
    _, outsider = await register(client, "outsider")
    params = {"workspace_id": world.workspace_id, "query": "salary"}
    assert (await client.get(f"{API}/retrieval/explain", params=params, headers=outsider)).status_code == 404
    assert (await client.get(f"{API}/retrieval/explain", params=params)).status_code == 401


async def test_outsiders_cannot_see_the_workspace_at_all(client: httpx.AsyncClient, world: World) -> None:
    _, outsider = await register(client, "outsider")
    doc_ids, chunk_ids = await confidential_ids(client, world)
    general_docs = (await client.get(f"{API}/collections/{world.general_id}/documents", headers=world.admin)).json()
    assert (await client.get(f"{API}/workspaces/{world.workspace_id}/collections", headers=outsider)).status_code == 404
    assert (
        await client.post(
            f"{API}/ask", json={"workspace_id": world.workspace_id, "question": "parental leave?"}, headers=outsider
        )
    ).status_code == 404
    for path in (
        f"/documents/{general_docs[0]['id']}",
        f"/documents/{general_docs[0]['id']}/chunks",
        f"/chunks/{chunk_ids[0]}",
        f"/documents/{doc_ids[0]}/file",
    ):
        assert (await client.get(f"{API}{path}", headers=outsider)).status_code == 404
    assert (await client.get(f"{API}/workspaces/{world.workspace_id}/members", headers=outsider)).status_code == 404


async def test_unauthenticated_requests_are_rejected_everywhere(client: httpx.AsyncClient, world: World) -> None:
    doc_ids, chunk_ids = await confidential_ids(client, world)
    for path in (
        f"/documents/{doc_ids[0]}",
        f"/chunks/{chunk_ids[0]}",
        f"/workspaces/{world.workspace_id}/collections",
        "/auth/me",
    ):
        assert (await client.get(f"{API}{path}")).status_code == 401
    assert (
        await client.post(f"{API}/ask", json={"workspace_id": world.workspace_id, "question": "anything?"})
    ).status_code == 401
    assert (
        await client.get(f"{API}/chunks/{chunk_ids[0]}", headers={"Authorization": "Bearer not-a-token"})
    ).status_code == 401


# --- stored answers are re-checked when access changes ---------------------------------------
async def test_revoking_access_removes_confidential_citations_from_stored_answers(
    client: httpx.AsyncClient, app: Any
) -> None:
    workspace_id, admin, general_id = await new_workspace(client)
    hr_email, hr = await register(client, "hr")
    await client.post(f"{API}/workspaces/{workspace_id}/members", json={"email": hr_email, "role": "member"}, headers=admin)
    group = (await client.post(f"{API}/workspaces/{workspace_id}/groups", json={"name": "hr"}, headers=admin)).json()
    other = (await client.post(f"{API}/workspaces/{workspace_id}/groups", json={"name": "finance"}, headers=admin)).json()
    await client.post(f"{API}/groups/{group['id']}/members", json={"email": hr_email}, headers=admin)
    secret = (
        await client.post(
            f"{API}/workspaces/{workspace_id}/collections",
            json={"name": "Secret", "visibility": "groups", "group_ids": [group["id"]]},
            headers=admin,
        )
    ).json()
    upload = await client.post(
        f"{API}/collections/{secret['id']}/documents",
        files={
            "file": (
                "secret.md",
                b"# Secret Plan\n\nThe launch codename is Bluebird and the budget is 900 thousand dollars.",
                "text/markdown",
            )
        },
        headers=admin,
    )
    assert upload.status_code == 202
    await ingest_all(app)

    question = {"workspace_id": workspace_id, "question": "What is the launch codename?"}
    before = (await client.post(f"{API}/ask", json=question, headers=hr)).json()
    assert before["status"] == "answered"
    assert "Bluebird" in before["claims"][0]["text"]

    # The admin moves the collection to another group: hr loses access.
    patch = await client.patch(f"{API}/collections/{secret['id']}", json={"group_ids": [other["id"]]}, headers=admin)
    assert patch.status_code == 200

    stored = (await client.get(f"{API}/answers/{before['id']}", headers=hr)).json()
    assert stored["status"] == "refused" and stored["claims"] == []
    assert "Bluebird" not in all_text(stored)
    thread = (await client.get(f"{API}/threads/{before['thread_id']}", headers=hr)).json()
    assert "Bluebird" not in all_text(thread)
    assert (await client.post(f"{API}/ask", json=question, headers=hr)).json()["status"] == "refused"


async def test_a_collection_cannot_be_opened_to_a_group_from_another_workspace(client: httpx.AsyncClient) -> None:
    ws_a, admin_a, _ = await new_workspace(client)
    ws_b, admin_b, _ = await new_workspace(client)
    foreign = (await client.post(f"{API}/workspaces/{ws_b}/groups", json={"name": "hr"}, headers=admin_b)).json()
    response = await client.post(
        f"{API}/workspaces/{ws_a}/collections",
        json={"name": "Sneaky", "visibility": "groups", "group_ids": [foreign["id"]]},
        headers=admin_a,
    )
    assert response.status_code == 422
