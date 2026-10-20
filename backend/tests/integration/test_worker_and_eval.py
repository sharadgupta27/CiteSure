"""The Postgres job queue (SKIP LOCKED, retries) and the evaluation flow through the API and the worker."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from sqlalchemy import select, text

from app.models import Job
from app.repositories import jobs as jobs_repo
from app.worker import drain, process_one
from tests.conftest import World

API = "/api/v1"


async def clear_jobs(app: Any) -> None:
    await drain(app.state.sessionmaker, app.state.providers, app.state.settings)
    async with app.state.sessionmaker() as session:
        await session.execute(text("DELETE FROM jobs"))
        await session.commit()


# --- queue ------------------------------------------------------------------------------------
async def test_concurrent_workers_never_claim_the_same_job(app: Any) -> None:
    await clear_jobs(app)
    sessionmaker = app.state.sessionmaker
    async with sessionmaker() as session:
        ids = {await jobs_repo.enqueue(session, "noop", {"n": i}) for i in range(8)}
        await session.commit()

    async def claim() -> Any:
        async with sessionmaker() as session:
            job = await jobs_repo.claim_next(session)
            await session.commit()
            return job

    claimed = await asyncio.gather(*(claim() for _ in range(8)))
    claimed_ids = [j.id for j in claimed if j is not None]
    assert len(claimed_ids) == 8 and set(claimed_ids) == ids  # every job claimed exactly once
    assert await claim() is None
    await clear_jobs(app)


async def test_failed_jobs_retry_with_backoff_then_fail_for_good(app: Any) -> None:
    await clear_jobs(app)
    sessionmaker = app.state.sessionmaker
    async with sessionmaker() as session:
        job_id = await jobs_repo.enqueue(session, "unknown-kind", {}, max_attempts=2)
        await session.commit()

    assert await process_one(sessionmaker, app.state.providers, app.state.settings) is True
    async with sessionmaker() as session:
        job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()
        assert job.status == "queued" and job.attempts == 1 and "Unknown job kind" in (job.error or "")
        assert job.run_after.timestamp() > job.created_at.timestamp() + 5  # backoff pushed it into the future
    assert await process_one(sessionmaker, app.state.providers, app.state.settings) is False  # not due yet

    async with sessionmaker() as session:
        await session.execute(text("UPDATE jobs SET run_after = now() WHERE id = :id"), {"id": job_id})
        await session.commit()
    assert await process_one(sessionmaker, app.state.providers, app.state.settings) is True
    async with sessionmaker() as session:
        job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()
        assert job.status == "failed" and job.attempts == 2
    await clear_jobs(app)


async def test_a_job_stuck_in_running_is_recovered(app: Any) -> None:
    await clear_jobs(app)
    sessionmaker = app.state.sessionmaker
    async with sessionmaker() as session:
        job_id = await jobs_repo.enqueue(session, "noop", {})
        await session.execute(
            text("UPDATE jobs SET status = 'running', locked_at = now() - interval '1 hour' WHERE id = :id"), {"id": job_id}
        )
        await session.commit()
    async with sessionmaker() as session:  # a worker crashed an hour ago; another worker picks the job up
        job = await jobs_repo.claim_next(session)
        await session.commit()
    assert job is not None and job.id == job_id
    await clear_jobs(app)


# --- evaluation through the API ---------------------------------------------------------------
async def run_eval(client: httpx.AsyncClient, app: Any, world: World, name: str, config: dict[str, Any]) -> dict[str, Any]:
    created = await client.post(
        f"{API}/workspaces/{world.workspace_id}/eval-runs", json={"name": name, "config": config}, headers=world.admin
    )
    assert created.status_code == 202 and created.json()["status"] == "queued"
    await drain(app.state.sessionmaker, app.state.providers, app.state.settings)
    run = (await client.get(f"{API}/eval-runs/{created.json()['id']}", headers=world.admin)).json()
    assert run["status"] == "done", run["error"]
    return run


HYBRID = {"retrieval_mode": "hybrid", "rerank": True, "candidate_k": 30, "top_k": 6}
VECTOR = {"retrieval_mode": "vector", "rerank": False, "candidate_k": 30, "top_k": 6}


async def test_eval_run_scores_the_golden_set_and_never_answers_restricted_questions(
    client: httpx.AsyncClient, app: Any, world: World
) -> None:
    run = await run_eval(client, app, world, "hybrid+rerank", HYBRID)
    metrics = run["metrics"]
    assert metrics["n_questions"] == 40
    assert metrics["restricted_refusal_accuracy"] == 1.0  # the hard gate
    assert metrics["recall_at_k"] >= 0.9 and metrics["mrr"] >= 0.8
    assert metrics["faithfulness"] == 1.0
    assert metrics["refusal_accuracy"] >= 0.8
    assert len(run["items"]) == 40
    restricted = [i for i in run["items"] if not i["answerable"] and i["scores"]["refused"] == 0.0]
    assert all("restricted" not in i["question"].lower() for i in restricted)


async def test_two_runs_can_be_compared(client: httpx.AsyncClient, app: Any, world: World) -> None:
    base = await run_eval(client, app, world, "vector-only", VECTOR)
    head = await run_eval(client, app, world, "hybrid+rerank", HYBRID)
    comparison = (
        await client.get(f"{API}/eval-runs/compare", params={"base": base["id"], "head": head["id"]}, headers=world.admin)
    ).json()
    assert comparison["base"]["name"] == "vector-only" and comparison["head"]["name"] == "hybrid+rerank"
    assert comparison["deltas"]["mrr"] == round(head["metrics"]["mrr"] - base["metrics"]["mrr"], 4)
    listing = (await client.get(f"{API}/workspaces/{world.workspace_id}/eval-runs", headers=world.admin)).json()
    assert {base["id"], head["id"]} <= {r["id"] for r in listing}


async def test_evaluation_is_admin_only(client: httpx.AsyncClient, world: World) -> None:
    for headers in (world.employee, world.hr):
        base = f"{API}/workspaces/{world.workspace_id}"
        assert (
            await client.post(f"{base}/eval-runs", json={"name": "x", "config": HYBRID}, headers=headers)
        ).status_code == 403
        assert (await client.get(f"{base}/eval-runs", headers=headers)).status_code == 403
        assert (await client.get(f"{base}/golden-questions", headers=headers)).status_code == 403
    assert (
        await client.get(
            f"{API}/eval-runs/compare", params={"base": world.workspace_id, "head": world.workspace_id}, headers=world.admin
        )
    ).status_code == 404


async def test_golden_questions_need_a_reason_and_expected_quotes(client: httpx.AsyncClient, world: World) -> None:
    url = f"{API}/workspaces/{world.workspace_id}/golden-questions"
    body = {
        "question": "How many sick days do I get?",
        "expected_answer": "10",
        "expected_quotes": [],
        "answerable": True,
        "ask_as": None,
        "tags": [],
        "reason": "why",
    }
    assert (await client.post(url, json=body, headers=world.admin)).status_code == 422  # answerable but no expected quote
    body["expected_quotes"] = [{"document": "vacation-and-pto.md", "quote": "Employees receive 10 paid sick days per year."}]
    body["reason"] = ""
    assert (await client.post(url, json=body, headers=world.admin)).status_code == 422  # no reason
    body["reason"] = "Missing coverage for sick leave."
    created = await client.post(url, json=body, headers=world.admin)
    assert created.status_code == 201
    updated = await client.patch(
        f"{API}/golden-questions/{created.json()['id']}",
        json={"expected_answer": "10 days", "reason": "Clarified the answer."},
        headers=world.admin,
    )
    assert updated.status_code == 200 and updated.json()["expected_answer"] == "10 days"
    assert (
        "Clarified" in updated.json()["reason"] and "Missing coverage" in updated.json()["reason"]
    )  # history of why it changed
    assert (
        await client.patch(
            f"{API}/golden-questions/{created.json()['id']}", json={"expected_answer": "x"}, headers=world.admin
        )
    ).status_code == 422
    assert (await client.delete(f"{API}/golden-questions/{created.json()['id']}", headers=world.admin)).status_code == 204


async def test_eval_run_with_an_empty_golden_set_fails_cleanly(client: httpx.AsyncClient, app: Any) -> None:
    from tests.conftest import new_workspace

    workspace_id, admin, _ = await new_workspace(client)
    created = await client.post(
        f"{API}/workspaces/{workspace_id}/eval-runs", json={"name": "empty", "config": HYBRID}, headers=admin
    )
    await drain(app.state.sessionmaker, app.state.providers, app.state.settings)
    run = (await client.get(f"{API}/eval-runs/{created.json()['id']}", headers=admin)).json()
    assert run["status"] == "failed" and "empty" in run["error"]


async def test_evaluator_personas_never_leak_into_member_or_group_lists(
    client: httpx.AsyncClient, app: Any, world: World
) -> None:
    """Regression: the synthetic eval users (…@citesure.invalid) made GET /members crash with a 500 once an eval had run."""
    await run_eval(client, app, world, "persona-check", HYBRID)
    members = await client.get(f"{API}/workspaces/{world.workspace_id}/members", headers=world.admin)
    assert members.status_code == 200
    emails = {m["email"] for m in members.json()}
    assert emails == {
        "admin@acme.example",
        "employee@acme.example",
        "hr@acme.example",
        "agent@acme.example",
    }  # agent@ is the MCP service user; no eval-*@citesure.invalid persona
    groups = (await client.get(f"{API}/workspaces/{world.workspace_id}/groups", headers=world.admin)).json()
    hr = next(g for g in groups if g["name"] == "hr")
    member_ids = {m["user_id"] for m in members.json()}
    assert len(hr["member_ids"]) == 1 and set(hr["member_ids"]) <= member_ids
