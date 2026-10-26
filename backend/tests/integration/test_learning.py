"""Learning layer, end to end: reading progress, study sets, learning plans, summarize and compare."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import text

from app.llm.fake import FakeProvider
from tests.integration.learning_helpers import (
    API,
    SECURITY,
    SECURITY_OLD,
    VACATION,
    Lab,
    make_lab,
    quotes_of,
)


async def set_page_count(app: Any, document_id: str, pages: int | None) -> None:
    async with app.state.sessionmaker() as session:
        await session.execute(text("UPDATE documents SET page_count = :n WHERE id = :id"), {"n": pages, "id": document_id})
        await session.commit()


async def chunk_text(client: httpx.AsyncClient, headers: dict[str, str], chunk_id: str) -> str:
    response = await client.get(f"{API}/chunks/{chunk_id}", headers=headers)
    assert response.status_code == 200
    return response.json()["text"]  # type: ignore[no-any-return]


async def create_set(
    client: httpx.AsyncClient, lab: Lab, name: str, docs: list[str], headers: dict[str, str] | None = None
) -> dict[str, Any]:
    headers = headers or lab.admin
    created = await client.post(f"{API}/workspaces/{lab.workspace_id}/study-sets", json={"name": name}, headers=headers)
    assert created.status_code == 201, created.text
    for name_ in docs:
        added = await client.post(
            f"{API}/study-sets/{created.json()['id']}/items", json={"document_id": lab.doc(name_)}, headers=headers
        )
        assert added.status_code == 201, added.text
    return created.json()  # type: ignore[no-any-return]


# --- reading progress -------------------------------------------------------------------------------
async def test_progress_starts_empty_and_accumulates_pages(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    doc = lab.doc("vacation.md")
    await set_page_count(app, doc, 4)
    empty = (await client.get(f"{API}/documents/{doc}/progress", headers=lab.member)).json()
    assert empty["percent"] == 0 and empty["pages_read"] == [] and empty["last_opened_at"] is None

    first = await client.put(f"{API}/documents/{doc}/progress", json={"page": 1, "mark_read": True}, headers=lab.member)
    assert first.status_code == 200
    second = await client.put(f"{API}/documents/{doc}/progress", json={"page": 3, "mark_read": True}, headers=lab.member)
    body = second.json()
    assert body["pages_read"] == [1, 3] and body["last_page"] == 3 and body["percent"] == 50.0
    assert body["last_opened_at"] is not None

    only_bookmark = await client.put(f"{API}/documents/{doc}/progress", json={"page": 2}, headers=lab.member)
    assert only_bookmark.json()["pages_read"] == [1, 3] and only_bookmark.json()["last_page"] == 2
    again = (await client.get(f"{API}/documents/{doc}/progress", headers=lab.member)).json()
    assert again["pages_read"] == [1, 3] and again["last_page"] == 2


async def test_progress_without_pages_keeps_the_furthest_percent(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    doc = lab.doc("vacation.md")
    await client.put(f"{API}/documents/{doc}/progress", json={"percent": 60}, headers=lab.member)
    body = (await client.put(f"{API}/documents/{doc}/progress", json={"percent": 20}, headers=lab.member)).json()
    assert body["percent"] == 60


async def test_progress_can_be_reset(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    doc = lab.doc("vacation.md")
    await client.put(f"{API}/documents/{doc}/progress", json={"percent": 60}, headers=lab.member)
    assert (await client.delete(f"{API}/documents/{doc}/progress", headers=lab.member)).status_code == 204
    assert (await client.get(f"{API}/documents/{doc}/progress", headers=lab.member)).json()["percent"] == 0


async def test_progress_is_private_to_each_user(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    doc = lab.doc("vacation.md")
    await client.put(f"{API}/documents/{doc}/progress", json={"percent": 70}, headers=lab.admin)
    assert (await client.get(f"{API}/documents/{doc}/progress", headers=lab.member)).json()["percent"] == 0
    assert (await client.get(f"{API}/workspaces/{lab.workspace_id}/reading-progress", headers=lab.member)).json() == []
    mine = (await client.get(f"{API}/workspaces/{lab.workspace_id}/reading-progress", headers=lab.admin)).json()
    assert [(p["document_id"], p["percent"], p["document_title"]) for p in mine] == [(doc, 70, "Vacation Policy")]


async def test_recent_reading_is_most_recent_first(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    for name in ("vacation.md", "security.md", "vacation.md"):
        await client.put(f"{API}/documents/{lab.doc(name)}/progress", json={"percent": 5}, headers=lab.member)
    rows = (await client.get(f"{API}/workspaces/{lab.workspace_id}/reading-progress", headers=lab.member)).json()
    assert [r["document_id"] for r in rows] == [lab.doc("vacation.md"), lab.doc("security.md")]


async def test_progress_validation(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    doc = lab.doc("vacation.md")
    for bad in ({"page": 0}, {"percent": 101}, {"pages_read": [0]}):
        assert (await client.put(f"{API}/documents/{doc}/progress", json=bad, headers=lab.member)).status_code == 422
    assert (await client.get(f"{API}/documents/{doc}/progress")).status_code == 401


# --- study sets -------------------------------------------------------------------------------------
async def test_study_set_with_documents_notes_and_rollup(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    study_set = await create_set(client, lab, "Onboarding", ["vacation.md", "security.md"])
    detail = (await client.get(f"{API}/study-sets/{study_set['id']}", headers=lab.admin)).json()
    assert [i["title"] for i in detail["items"]] == ["Vacation Policy", "Security Policy"]
    assert detail["item_count"] == 2 and detail["progress"]["documents_total"] == 2 and detail["progress"]["percent"] == 0

    await client.put(f"{API}/documents/{lab.doc('vacation.md')}/progress", json={"percent": 100}, headers=lab.admin)
    await client.put(f"{API}/documents/{lab.doc('security.md')}/progress", json={"percent": 40}, headers=lab.admin)
    detail = (await client.get(f"{API}/study-sets/{study_set['id']}", headers=lab.admin)).json()
    assert detail["progress"] == {"documents_total": 2, "documents_started": 2, "documents_finished": 1, "percent": 70.0}
    assert [i["percent"] for i in detail["items"]] == [100, 40]

    patched = await client.patch(
        f"{API}/study-sets/{study_set['id']}",
        json={"notes": "Read before day one", "description": "New hires"},
        headers=lab.admin,
    )
    assert patched.json()["notes"] == "Read before day one" and patched.json()["description"] == "New hires"
    listed = (await client.get(f"{API}/workspaces/{lab.workspace_id}/study-sets", headers=lab.admin)).json()
    assert [s["name"] for s in listed] == ["Onboarding"] and "items" not in listed[0]
    assert listed[0]["progress"]["percent"] == 70.0


async def test_study_set_items_can_be_noted_moved_and_removed(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    study_set = await create_set(client, lab, "Order", ["vacation.md", "security.md"])
    items = (await client.get(f"{API}/study-sets/{study_set['id']}", headers=lab.admin)).json()["items"]
    moved = await client.patch(
        f"{API}/study-sets/{study_set['id']}/items/{items[1]['id']}",
        json={"position": 0, "note": "start here"},
        headers=lab.admin,
    )
    assert moved.status_code == 200 and moved.json()["note"] == "start here"
    reordered = (await client.get(f"{API}/study-sets/{study_set['id']}", headers=lab.admin)).json()["items"]
    assert [i["title"] for i in reordered] == ["Security Policy", "Vacation Policy"]
    removed = await client.delete(f"{API}/study-sets/{study_set['id']}/items/{items[0]['id']}", headers=lab.admin)
    assert removed.status_code == 204
    assert len((await client.get(f"{API}/study-sets/{study_set['id']}", headers=lab.admin)).json()["items"]) == 1
    assert (
        await client.delete(f"{API}/study-sets/{study_set['id']}/items/{items[0]['id']}", headers=lab.admin)
    ).status_code == 404


async def test_a_public_paper_can_be_saved_by_reference_only(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    study_set = await create_set(client, lab, "Papers", [])
    ref = {"title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762", "source": "arxiv"}
    added = await client.post(
        f"{API}/study-sets/{study_set['id']}/items", json={"reference": ref, "note": "classic"}, headers=lab.admin
    )
    assert added.status_code == 201
    item = added.json()
    assert (
        item["kind"] == "reference" and item["document_id"] is None and item["url"] == ref["url"] and item["percent"] is None
    )
    detail = (await client.get(f"{API}/study-sets/{study_set['id']}", headers=lab.admin)).json()
    assert detail["item_count"] == 1 and detail["progress"]["documents_total"] == 0  # references are not reading progress
    for bad in ({"title": "x", "url": "javascript:alert(1)"}, {"title": "x", "url": "ftp://example.com/paper"}):
        response = await client.post(f"{API}/study-sets/{study_set['id']}/items", json={"reference": bad}, headers=lab.admin)
        assert response.status_code == 422


async def test_study_set_input_rules(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    study_set = await create_set(client, lab, "Rules", ["vacation.md"])
    base = f"{API}/workspaces/{lab.workspace_id}/study-sets"
    assert (await client.post(base, json={"name": "Rules"}, headers=lab.admin)).status_code == 409
    assert (await client.post(base, json={"name": "Rules"}, headers=lab.member)).status_code == 201  # names are per user
    assert (await client.post(base, json={"name": "  "}, headers=lab.admin)).status_code == 422
    assert (await client.post(base, json={"name": ""}, headers=lab.admin)).status_code == 422
    dup = await client.post(
        f"{API}/study-sets/{study_set['id']}/items", json={"document_id": lab.doc("vacation.md")}, headers=lab.admin
    )
    assert dup.status_code == 409
    neither = await client.post(f"{API}/study-sets/{study_set['id']}/items", json={}, headers=lab.admin)
    assert neither.status_code == 422
    other = await create_set(client, lab, "Other", [])
    assert (
        await client.patch(f"{API}/study-sets/{other['id']}", json={"name": "Rules"}, headers=lab.admin)
    ).status_code == 409
    assert (await client.delete(f"{API}/study-sets/{study_set['id']}", headers=lab.admin)).status_code == 204
    assert (await client.get(f"{API}/study-sets/{study_set['id']}", headers=lab.admin)).status_code == 404
    # deleting a set never deletes documents
    assert (await client.get(f"{API}/documents/{lab.doc('vacation.md')}", headers=lab.admin)).status_code == 200


# --- learning plans ---------------------------------------------------------------------------------
async def test_plan_from_a_study_set_has_verified_objectives(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    study_set = await create_set(client, lab, "Policies", ["vacation.md", "security.md"])
    response = await client.post(
        f"{API}/workspaces/{lab.workspace_id}/learning-plans",
        json={"study_set_id": study_set["id"], "hours_per_week": 2},
        headers=lab.admin,
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["title"] == "Policies" and plan["study_set_id"] == study_set["id"] and plan["topic"] is None
    assert [s["document_title"] for s in plan["steps"]] == ["Vacation Policy", "Security Policy"]  # study set order is kept
    assert plan["steps_total"] == 2 and plan["steps_done"] == 0 and plan["percent"] == 0 and plan["weeks"] == 1
    assert [s["position"] for s in plan["steps"]] == [1, 2]
    for step in plan["steps"]:
        assert step["est_minutes"] >= 1 and step["week"] == 1 and step["done"] is False
        objective = step["objective"]
        assert objective["status"] == "answered" and objective["claims"]
        for claim in objective["claims"]:
            assert claim["verified"] is True and claim["verification"]["entailment"] == "supported"
            for citation in claim["citations"]:
                assert citation["document_id"] == step["document_id"]
                assert citation["quote"] in await chunk_text(client, lab.admin, citation["chunk_id"])
    # the same plan is readable again, and listed
    again = (await client.get(f"{API}/learning-plans/{plan['id']}", headers=lab.admin)).json()
    assert again["steps"][0]["objective"]["claims"] == plan["steps"][0]["objective"]["claims"]
    listed = (await client.get(f"{API}/workspaces/{lab.workspace_id}/learning-plans", headers=lab.admin)).json()
    assert [p["id"] for p in listed] == [plan["id"]] and "steps" not in listed[0]


async def test_long_documents_become_several_steps_spread_over_weeks(client: httpx.AsyncClient, app: Any) -> None:
    sections = "\n\n".join(
        f"## Chapter {n}\n\n"
        + " ".join(f"Chapter {n} explains item {n}{i} of the handbook in some detail." for i in range(45))
        for n in range(1, 5)
    )
    lab = await make_lab(client, app, {"handbook.md": f"# Handbook\n\n{sections}"})
    app.state.settings.learning_unit_minutes = 5
    try:
        response = await client.post(
            f"{API}/workspaces/{lab.workspace_id}/learning-plans",
            json={"document_ids": [lab.doc("handbook.md")], "hours_per_week": 0.1, "title": "Handbook"},
            headers=lab.admin,
        )
    finally:
        app.state.settings.learning_unit_minutes = 30
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["title"] == "Handbook"
    assert len(plan["steps"]) >= 2
    assert plan["weeks"] >= 2 and plan["steps"][-1]["week"] == plan["weeks"]  # 6 minutes a week cannot hold them all
    assert len({s["label"] for s in plan["steps"]}) == len(plan["steps"])  # each step names its own sections
    assert plan["total_minutes"] == sum(s["est_minutes"] for s in plan["steps"])


async def test_steps_can_be_completed_and_reopened(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    study_set = await create_set(client, lab, "Policies", ["vacation.md", "security.md"])
    plan = (
        await client.post(
            f"{API}/workspaces/{lab.workspace_id}/learning-plans", json={"study_set_id": study_set["id"]}, headers=lab.admin
        )
    ).json()
    first = plan["steps"][0]["id"]
    done = await client.patch(f"{API}/learning-plans/{plan['id']}/steps/{first}", json={"done": True}, headers=lab.admin)
    assert done.status_code == 200
    body = done.json()
    assert (
        body["steps_done"] == 1
        and body["percent"] == 50.0
        and body["steps"][0]["done"] is True
        and body["steps"][0]["done_at"]
    )
    summary = (await client.get(f"{API}/workspaces/{lab.workspace_id}/learning-plans", headers=lab.admin)).json()[0]
    assert summary["steps_done"] == 1 and summary["percent"] == 50.0
    reopened = await client.patch(
        f"{API}/learning-plans/{plan['id']}/steps/{first}", json={"done": False}, headers=lab.admin
    )
    assert reopened.json()["steps_done"] == 0 and reopened.json()["steps"][0]["done_at"] is None
    missing = await client.patch(
        f"{API}/learning-plans/{plan['id']}/steps/{uuid.uuid4()}", json={"done": True}, headers=lab.admin
    )
    assert missing.status_code == 404


async def test_plan_steps_show_the_users_reading_progress(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    plan = (
        await client.post(
            f"{API}/workspaces/{lab.workspace_id}/learning-plans",
            json={"document_ids": [lab.doc("vacation.md")]},
            headers=lab.admin,
        )
    ).json()
    await client.put(f"{API}/documents/{lab.doc('vacation.md')}/progress", json={"percent": 35}, headers=lab.admin)
    refreshed = (await client.get(f"{API}/learning-plans/{plan['id']}", headers=lab.admin)).json()
    assert refreshed["steps"][0]["reading_percent"] == 35


async def test_a_topic_plan_keeps_only_steps_with_supported_statements_about_the_topic(
    client: httpx.AsyncClient, app: Any
) -> None:
    lab = await make_lab(client, app)
    response = await client.post(
        f"{API}/workspaces/{lab.workspace_id}/learning-plans",
        json={"topic": "paid vacation", "document_ids": [lab.doc("vacation.md"), lab.doc("security.md")]},
        headers=lab.admin,
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["topic"] == "paid vacation" and plan["title"] == "paid vacation"
    assert {s["document_title"] for s in plan["steps"]} == {"Vacation Policy"}  # the security policy says nothing about it
    assert all(s["objective"]["status"] == "answered" for s in plan["steps"])


async def test_a_topic_nothing_supports_is_refused_not_invented(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    response = await client.post(
        f"{API}/workspaces/{lab.workspace_id}/learning-plans",
        json={"topic": "quantum chromodynamics", "document_ids": [lab.doc("vacation.md")]},
        headers=lab.admin,
    )
    assert response.status_code == 422
    assert (await client.get(f"{API}/workspaces/{lab.workspace_id}/learning-plans", headers=lab.admin)).json() == []


async def test_a_dishonest_model_cannot_put_unsupported_text_in_a_plan(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    study_set = await create_set(client, lab, "Policies", ["vacation.md"])
    app.state.providers.llm = FakeProvider(mode="hallucinate")
    plan = (
        await client.post(
            f"{API}/workspaces/{lab.workspace_id}/learning-plans", json={"study_set_id": study_set["id"]}, headers=lab.admin
        )
    ).json()
    step = plan["steps"][0]
    assert step["document_title"] == "Vacation Policy" and step["est_minutes"] >= 1  # the structure is still useful
    assert step["objective"]["status"] == "refused" and step["objective"]["claims"] == []
    assert "42 days" not in str(plan)


async def test_a_failing_model_fails_the_request_and_stores_nothing(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)

    class Broken(FakeProvider):
        async def generate_answer(self, request):  # type: ignore[no-untyped-def]
            raise RuntimeError("model is down: secret document text should never be echoed")

    app.state.providers.llm = Broken()
    response = await client.post(
        f"{API}/workspaces/{lab.workspace_id}/learning-plans",
        json={"document_ids": [lab.doc("vacation.md")]},
        headers=lab.admin,
    )
    assert response.status_code == 502 and "secret" not in response.text
    assert (await client.get(f"{API}/workspaces/{lab.workspace_id}/learning-plans", headers=lab.admin)).json() == []


async def test_plan_input_rules(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    url = f"{API}/workspaces/{lab.workspace_id}/learning-plans"
    assert (await client.post(url, json={}, headers=lab.admin)).status_code == 422
    empty = await create_set(client, lab, "Empty", [])
    assert (await client.post(url, json={"study_set_id": empty["id"]}, headers=lab.admin)).status_code == 422
    both = {"study_set_id": empty["id"], "document_ids": [lab.doc("vacation.md")]}
    assert (await client.post(url, json=both, headers=lab.admin)).status_code == 422


async def test_deleting_a_plan_removes_its_generated_text(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    plan = (
        await client.post(
            f"{API}/workspaces/{lab.workspace_id}/learning-plans",
            json={"document_ids": [lab.doc("vacation.md")]},
            headers=lab.admin,
        )
    ).json()
    answer_id = plan["steps"][0]["objective"]["id"]
    assert (await client.get(f"{API}/answers/{answer_id}", headers=lab.admin)).status_code == 200
    assert (await client.delete(f"{API}/learning-plans/{plan['id']}", headers=lab.admin)).status_code == 204
    assert (await client.get(f"{API}/learning-plans/{plan['id']}", headers=lab.admin)).status_code == 404
    assert (await client.get(f"{API}/answers/{answer_id}", headers=lab.admin)).status_code == 404


async def test_deleting_a_document_erases_its_quotes_from_plans(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    plan = (
        await client.post(
            f"{API}/workspaces/{lab.workspace_id}/learning-plans",
            json={"document_ids": [lab.doc("vacation.md"), lab.doc("security.md")]},
            headers=lab.admin,
        )
    ).json()
    vacation_step = next(s for s in plan["steps"] if s["document_title"] == "Vacation Policy")
    answer_id = vacation_step["objective"]["id"]
    assert (await client.delete(f"{API}/documents/{lab.doc('vacation.md')}", headers=lab.admin)).status_code == 204
    after = (await client.get(f"{API}/learning-plans/{plan['id']}", headers=lab.admin)).json()
    assert [s["document_title"] for s in after["steps"]] == ["Security Policy"] and after["steps_total"] == 1
    erased = (await client.get(f"{API}/answers/{answer_id}", headers=lab.admin)).json()
    assert erased["claims"] == [] and "25 days" not in str(erased)


# --- summarize and compare --------------------------------------------------------------------------
async def test_a_summary_is_an_ordinary_verified_answer(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    response = await client.post(
        f"{API}/workspaces/{lab.workspace_id}/learning/summarize",
        json={"document_id": lab.doc("vacation.md")},
        headers=lab.member,
    )
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["status"] == "answered" and answer["scope"] == "internal" and answer["egress"] == []
    assert answer["claims"] and all(c["verified"] for c in answer["claims"])
    chunk_texts = [
        await chunk_text(client, lab.member, c["chunk_id"]) for claim in answer["claims"] for c in claim["citations"]
    ]
    assert all(q in t for q, t in zip(quotes_of(answer), chunk_texts, strict=True))
    assert {c["document_id"] for claim in answer["claims"] for c in claim["citations"]} == {lab.doc("vacation.md")}
    stored = await client.get(f"{API}/answers/{answer['id']}", headers=lab.member)  # shows up like any other answer
    assert stored.status_code == 200 and stored.json()["claims"] == answer["claims"]
    assert (
        await client.get(f"{API}/answers/{answer['id']}", headers=lab.admin)
    ).status_code == 200  # admins read members' answers, as for /ask


async def test_a_summary_can_be_focused_and_says_when_it_read_only_part_of_a_document(
    client: httpx.AsyncClient, app: Any
) -> None:
    sections = "\n\n".join(
        f"## Part {n}\n\n" + " ".join(f"Part {n} describes widget {n}{i} and its settings." for i in range(30))
        for n in range(1, 6)
    )
    lab = await make_lab(client, app, {"manual.md": f"# Manual\n\n{sections}"})
    app.state.settings.learning_summary_chunks = 2
    try:
        plain = (
            await client.post(
                f"{API}/workspaces/{lab.workspace_id}/learning/summarize",
                json={"document_id": lab.doc("manual.md")},
                headers=lab.admin,
            )
        ).json()
        focused = (
            await client.post(
                f"{API}/workspaces/{lab.workspace_id}/learning/summarize",
                json={"document_id": lab.doc("manual.md"), "focus": "widget 41 settings"},
                headers=lab.admin,
            )
        ).json()
    finally:
        app.state.settings.learning_summary_chunks = 12
    assert plain["status"] == "answered" and any("sections of the document" in n for n in plain["notices"])
    assert focused["status"] == "answered" and any("best match the focus" in n for n in focused["notices"])


async def test_a_summary_of_something_the_document_never_says_is_refused(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    answer = (
        await client.post(
            f"{API}/workspaces/{lab.workspace_id}/learning/summarize",
            json={"document_id": lab.doc("vacation.md"), "focus": "nuclear reactor maintenance"},
            headers=lab.admin,
        )
    ).json()
    assert answer["status"] == "refused" and answer["claims"] == [] and answer["refusal"]["message"]


async def test_a_document_still_being_processed_cannot_be_summarized_yet(client: httpx.AsyncClient, app: Any) -> None:
    from tests.integration.learning_helpers import upload

    lab = await make_lab(client, app)
    pending = await upload(client, lab.admin, lab.collection_id, "pending.md", "# Pending\n\nNot indexed yet.")
    response = await client.post(
        f"{API}/workspaces/{lab.workspace_id}/learning/summarize", json={"document_id": pending["id"]}, headers=lab.admin
    )
    assert response.status_code == 409


async def test_comparison_cites_each_document_and_notes_those_that_say_nothing(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app, {"security.md": SECURITY, "security-2019.md": SECURITY_OLD, "vacation.md": VACATION})
    ids = [lab.doc("security.md"), lab.doc("security-2019.md"), lab.doc("vacation.md")]
    response = await client.post(
        f"{API}/workspaces/{lab.workspace_id}/learning/compare",
        json={"document_ids": ids, "aspect": "passwords rotated"},
        headers=lab.member,
    )
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["status"] == "answered"
    cited = {c["document_id"]: claim["text"] for claim in answer["claims"] for c in claim["citations"]}
    assert set(cited) == {ids[0], ids[1]}
    assert "90 days" in cited[ids[0]] and "180 days" in cited[ids[1]]
    assert answer["notices"] == ['No supported statement on this aspect was found in "Vacation Policy".']


async def test_comparison_of_an_aspect_nobody_covers_is_refused(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    answer = (
        await client.post(
            f"{API}/workspaces/{lab.workspace_id}/learning/compare",
            json={"document_ids": [lab.doc("vacation.md"), lab.doc("security.md")], "aspect": "submarine propulsion"},
            headers=lab.admin,
        )
    ).json()
    assert answer["status"] == "refused" and answer["claims"] == []


async def test_comparison_input_rules(client: httpx.AsyncClient, app: Any) -> None:
    lab = await make_lab(client, app)
    url = f"{API}/workspaces/{lab.workspace_id}/learning/compare"
    one = lab.doc("vacation.md")
    assert (await client.post(url, json={"document_ids": [one], "aspect": "leave"}, headers=lab.admin)).status_code == 422
    assert (
        await client.post(url, json={"document_ids": [one, one], "aspect": "leave"}, headers=lab.admin)
    ).status_code == 422
    assert (
        await client.post(url, json={"document_ids": [one, lab.doc("security.md")], "aspect": "x"}, headers=lab.admin)
    ).status_code == 422
    six = [str(uuid.uuid4()) for _ in range(6)]
    assert (await client.post(url, json={"document_ids": six, "aspect": "leave"}, headers=lab.admin)).status_code == 422
