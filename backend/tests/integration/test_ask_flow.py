"""Asking questions: answers with verified citations, streaming, threads, feedback, promotion to the golden set."""

from __future__ import annotations

from typing import Any

import httpx

from app.llm.fake import FakeProvider
from tests.conftest import World, ingest_all, new_workspace, parse_sse, register

API = "/api/v1"
QUESTION = "How many weeks of paid parental leave do primary caregivers get?"


async def ask(
    client: httpx.AsyncClient, world: World, question: str = QUESTION, headers: dict[str, str] | None = None, **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        f"{API}/ask",
        json={"workspace_id": world.workspace_id, "question": question, **extra},
        headers=headers or world.employee,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_the_happy_path_answer_has_verified_citations_pointing_at_real_text(
    client: httpx.AsyncClient, world: World
) -> None:
    answer = await ask(client, world)
    assert answer["status"] == "answered" and answer["refusal"] is None
    claim = answer["claims"][0]
    assert "16 weeks" in claim["text"]
    assert claim["verified"] is True
    assert claim["verification"]["entailment"] == "supported" and claim["verification"]["quote_match"] >= 0.9
    citation = claim["citations"][0]
    assert citation["document_title"] == "Parental Leave Policy"

    chunk = (await client.get(f"{API}/chunks/{citation['chunk_id']}", headers=world.employee)).json()
    highlighted = chunk["text"][citation["quote_start"] : citation["quote_end"]]
    assert "16 weeks of fully paid leave" in highlighted  # the viewer highlights exactly the cited words
    assert answer["latency_ms_by_stage"].keys() >= {"acl", "embed", "vector", "fts", "fuse", "rerank", "generate", "verify"}


async def test_unanswerable_questions_are_refused_with_closest_sources(client: httpx.AsyncClient, world: World) -> None:
    answer = await ask(client, world, "What is the company's sabbatical policy?")
    assert answer["status"] == "refused" and answer["claims"] == []
    assert answer["refusal"]["message"].startswith("I don't have information")
    assert answer["refusal"]["reason"] == "no_supported_claims"
    assert 0 < len(answer["refusal"]["closest_sources"]) <= 3


async def test_an_empty_workspace_gives_no_sources(client: httpx.AsyncClient) -> None:
    workspace_id, admin, _ = await new_workspace(client)
    response = await client.post(
        f"{API}/ask", json={"workspace_id": workspace_id, "question": "Anything at all in here?"}, headers=admin
    )
    assert response.json()["refusal"]["reason"] == "no_sources"


async def test_stream_events_arrive_in_order_and_match_the_final_answer(client: httpx.AsyncClient, world: World) -> None:
    response = await client.post(
        f"{API}/ask/stream", json={"workspace_id": world.workspace_id, "question": QUESTION}, headers=world.employee
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[:3] == ["stage", "stage", "stage"]
    assert [data for name, data in events if name == "stage"] == ["retrieving", "generating", "verifying"]
    assert names[-1] == "final" and names.count("final") == 1
    first_token = names.index("token")
    assert all(n == "token" for n in names[first_token:-1])
    streamed = "".join(data for name, data in events if name == "token")
    final = events[-1][1]
    assert streamed.strip().startswith(final["claims"][0]["text"])  # only verified text is ever streamed


async def test_stream_errors_before_the_first_event_are_real_http_errors(client: httpx.AsyncClient, world: World) -> None:
    ghost = "00000000-0000-0000-0000-000000000000"
    response = await client.post(
        f"{API}/ask/stream", json={"workspace_id": ghost, "question": QUESTION}, headers=world.employee
    )
    assert response.status_code == 404
    assert (
        await client.post(f"{API}/ask/stream", json={"workspace_id": ghost, "question": "x"}, headers=world.employee)
    ).status_code == 422


async def test_threads_keep_history_per_user(client: httpx.AsyncClient, world: World) -> None:
    first = await ask(client, world)
    follow_up = await ask(
        client, world, "How many unused PTO days can I carry over into the next year?", thread_id=first["thread_id"]
    )
    assert follow_up["thread_id"] == first["thread_id"]
    detail = (await client.get(f"{API}/threads/{first['thread_id']}", headers=world.employee)).json()
    assert [a["id"] for a in detail["answers"]] == [first["id"], follow_up["id"]]
    listing = (
        await client.get(f"{API}/threads", params={"workspace_id": world.workspace_id}, headers=world.employee)
    ).json()
    assert first["thread_id"] in [t["id"] for t in listing]

    assert (
        await client.get(f"{API}/threads/{first['thread_id']}", headers=world.hr)
    ).status_code == 404  # someone else's thread
    assert (await client.get(f"{API}/answers/{first['id']}", headers=world.hr)).status_code == 404
    assert (await client.get(f"{API}/answers/{first['id']}", headers=world.admin)).status_code == 200  # admins may audit
    stolen = await client.post(
        f"{API}/ask",
        json={"workspace_id": world.workspace_id, "question": QUESTION, "thread_id": first["thread_id"]},
        headers=world.hr,
    )
    assert stolen.status_code == 404


async def test_only_admins_can_override_the_pipeline_configuration(client: httpx.AsyncClient, world: World) -> None:
    config = {"retrieval_mode": "vector", "rerank": False, "candidate_k": 10, "top_k": 3}
    denied = await client.post(
        f"{API}/ask",
        json={"workspace_id": world.workspace_id, "question": QUESTION, "config": config},
        headers=world.employee,
    )
    assert denied.status_code == 403
    allowed = await client.post(
        f"{API}/ask", json={"workspace_id": world.workspace_id, "question": QUESTION, "config": config}, headers=world.admin
    )
    assert allowed.status_code == 200
    assert "fts" not in allowed.json()["latency_ms_by_stage"] and "rerank" not in allowed.json()["latency_ms_by_stage"]


async def test_input_validation(client: httpx.AsyncClient, world: World) -> None:
    for question in ("", "hi", "x" * 1001):
        r = await client.post(
            f"{API}/ask", json={"workspace_id": world.workspace_id, "question": question}, headers=world.employee
        )
        assert r.status_code == 422


async def test_feedback_flows_to_the_admin_queue_and_into_the_golden_set(client: httpx.AsyncClient, world: World) -> None:
    answer = await ask(client, world, "What is the company's sabbatical policy?")
    created = await client.post(
        f"{API}/answers/{answer['id']}/feedback",
        json={"rating": -1, "comment": "We do have sabbaticals after 5 years."},
        headers=world.employee,
    )
    assert created.status_code == 201
    feedback_id = created.json()["id"]
    assert (
        await client.post(
            f"{API}/answers/{answer['id']}/feedback", json={"rating": 5, "comment": None}, headers=world.employee
        )
    ).status_code == 422
    assert (
        await client.post(f"{API}/answers/{answer['id']}/feedback", json={"rating": 1, "comment": None}, headers=world.hr)
    ).status_code == 404

    assert (await client.get(f"{API}/workspaces/{world.workspace_id}/feedback", headers=world.employee)).status_code == 403
    queue = (await client.get(f"{API}/workspaces/{world.workspace_id}/feedback", headers=world.admin)).json()
    item = next(i for i in queue if i["id"] == feedback_id)
    assert (
        item["question"] == "What is the company's sabbatical policy?" and item["promoted"] is False and item["rating"] == -1
    )

    body = {
        "answerable": True,
        "expected_answer": "Sabbaticals are available after 5 years.",
        "expected_quotes": [
            {"document": "benefits.md", "quote": "Every employee has a learning budget of $1,500 per calendar year"}
        ],
        "ask_as": None,
        "reason": "User reported that the bot missed the sabbatical policy.",
    }
    promoted = await client.post(
        f"{API}/workspaces/{world.workspace_id}/golden-questions/from-feedback/{feedback_id}", json=body, headers=world.admin
    )
    assert promoted.status_code == 201
    assert promoted.json()["source"] == "feedback" and promoted.json()["reason"].startswith("User reported")
    again = await client.post(
        f"{API}/workspaces/{world.workspace_id}/golden-questions/from-feedback/{feedback_id}", json=body, headers=world.admin
    )
    assert again.status_code == 409
    queue = (await client.get(f"{API}/workspaces/{world.workspace_id}/feedback", headers=world.admin)).json()
    assert next(i for i in queue if i["id"] == feedback_id)["promoted"] is True
    await client.delete(
        f"{API}/golden-questions/{promoted.json()['id']}", headers=world.admin
    )  # keep the shared golden set clean


async def test_every_claim_in_every_answer_is_verified(client: httpx.AsyncClient, world: World, app: Any) -> None:
    """The invariant behind the product promise: nothing unverified is ever returned, whatever the model does."""
    questions = [
        QUESTION,
        "How many days of paid time off do I get each year?",
        "What is the daily meal limit when I travel for work?",
        "Who is the CEO?",
    ]
    for mode in ("extractive", "hallucinate", "mismatch"):
        app.state.providers.llm = FakeProvider(mode=mode)  # type: ignore[arg-type]
        for question in questions:
            answer = await ask(client, world, question)
            for claim in answer["claims"]:
                assert claim["verified"] is True and claim["citations"]
                assert claim["verification"]["quote_match"] >= 0.9 and claim["verification"]["entailment"] == "supported"
            if mode != "extractive":
                assert answer["status"] == "refused" and answer["dropped_claims"] >= 0


async def test_a_dishonest_model_is_caught_and_the_user_gets_a_refusal(
    client: httpx.AsyncClient, world: World, app: Any
) -> None:
    app.state.providers.llm = FakeProvider(mode="hallucinate")
    answer = await ask(client, world)
    assert answer["status"] == "refused" and answer["claims"] == []
    assert answer["dropped_claims"] >= 1  # the admin can see the model tried


async def test_answers_record_provenance_for_debugging(client: httpx.AsyncClient, world: World, app: Any) -> None:
    from sqlalchemy import select

    from app.models import Answer

    answer = await ask(client, world)
    async with app.state.sessionmaker() as session:
        row = (await session.execute(select(Answer).where(Answer.id == answer["id"]))).scalar_one()
    assert row.config_snapshot["retrieval_mode"] == "hybrid" and row.config_snapshot["prompt"] == "answer_v1"
    assert len(row.retrieved_chunk_ids) == 6
    assert row.latency_ms_by_stage["verify"] >= 0


async def test_uploaded_documents_become_answerable_after_ingestion(client: httpx.AsyncClient, app: Any) -> None:
    workspace_id, admin, collection_id = await new_workspace(client)
    _, member = await register(client, "member")
    email = (await client.get(f"{API}/auth/me", headers=member)).json()["email"]
    await client.post(f"{API}/workspaces/{workspace_id}/members", json={"email": email, "role": "member"}, headers=admin)
    question = {"workspace_id": workspace_id, "question": "How many days is the winter shutdown?"}

    assert (await client.post(f"{API}/ask", json=question, headers=member)).json()["status"] == "refused"
    await client.post(
        f"{API}/collections/{collection_id}/documents",
        files={
            "file": ("shutdown.md", b"# Winter\n\nThe winter shutdown lasts 4 days at the end of December.", "text/markdown")
        },
        headers=admin,
    )
    assert (await client.post(f"{API}/ask", json=question, headers=member)).json()[
        "status"
    ] == "refused"  # still queued: not searchable yet
    await ingest_all(app)
    answer = (await client.post(f"{API}/ask", json=question, headers=member)).json()
    assert answer["status"] == "answered" and "4 days" in answer["claims"][0]["text"]
