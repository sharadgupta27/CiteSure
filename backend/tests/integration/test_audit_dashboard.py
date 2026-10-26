"""Audit log (hash chain, append-only, scoping, export) and the admin dashboard, against real Postgres."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError

from app.services import audit
from tests.conftest import PASSWORD, ingest_all, new_workspace, register

API = "/api/v1"
SECRET_QUESTION = "What is the zebra-quartz-7731 retention schedule for the unicorn project?"


async def events(client: httpx.AsyncClient, headers: dict[str, str], workspace_id: str, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/workspaces/{workspace_id}/audit-events", params=params, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def add_member(client: httpx.AsyncClient, admin: dict[str, str], workspace_id: str, email: str) -> None:
    created = await client.post(
        f"{API}/workspaces/{workspace_id}/members", json={"email": email, "role": "member"}, headers=admin
    )
    assert created.status_code == 201, created.text


async def verify(client: httpx.AsyncClient, headers: dict[str, str], workspace_id: str) -> dict[str, Any]:
    response = await client.get(f"{API}/workspaces/{workspace_id}/audit-events/verify", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_sign_in_events_are_recorded_and_unknown_addresses_are_hashed(client: httpx.AsyncClient, app: Any) -> None:
    workspace_id, admin, _ = await new_workspace(client)
    me = (await client.get(f"{API}/auth/me", headers=admin)).json()
    await client.post(f"{API}/auth/login", json={"email": me["email"], "password": PASSWORD})
    await client.post(f"{API}/auth/login", json={"email": me["email"], "password": "wrong-password-1"})
    typo = f"typo-{uuid.uuid4().hex[:6]}@example.com"
    await client.post(f"{API}/auth/login", json={"email": typo, "password": "whatever-123"})

    mine = await events(client, admin, workspace_id, actor=me["email"])
    actions = [e["action"] for e in mine["items"]]
    assert actions.count(audit.LOGIN) == 1 and actions.count(audit.LOGIN_FAILED) == 1
    assert audit.REGISTER in actions and audit.WORKSPACE_CREATE in actions
    failed = next(e for e in mine["items"] if e["action"] == audit.LOGIN_FAILED)
    assert failed["metadata"] == {"known_account": True} and failed["actor_email"] == me["email"]

    async with app.state.sessionmaker() as session:
        dump = (
            await session.execute(text("SELECT coalesce(string_agg(actor_email || metadata::text, ' '), '') FROM audit_log"))
        ).scalar_one()
        unknown = (
            await session.execute(
                text(
                    "SELECT metadata FROM audit_log WHERE action = 'auth.login_failed' AND actor_id IS NULL ORDER BY seq DESC LIMIT 1"
                )
            )
        ).scalar_one()
    assert typo not in dump and "email_sha256" in unknown  # an address that is not an account is kept as a hash only
    assert unknown["known_account"] is False and unknown["email_sha256"] == audit.sha256_hex(typo)


async def test_admin_actions_leave_entries_and_no_question_or_document_text(client: httpx.AsyncClient, app: Any) -> None:
    workspace_id, admin, collection_id = await new_workspace(client)
    member_email, member = await register(client, "member")
    await add_member(client, admin, workspace_id, member_email)
    group = (await client.post(f"{API}/workspaces/{workspace_id}/groups", json={"name": "hr"}, headers=admin)).json()
    await client.post(f"{API}/groups/{group['id']}/members", json={"email": member_email}, headers=admin)

    body = b"# Zebra Quartz 7731\n\nThe unicorn retention schedule is forty two days."
    upload = await client.post(
        f"{API}/collections/{collection_id}/documents", files={"file": ("zebra.md", body, "text/markdown")}, headers=admin
    )
    assert upload.status_code == 202
    document = upload.json()
    await ingest_all(app)
    answer = (
        await client.post(f"{API}/ask", json={"workspace_id": workspace_id, "question": SECRET_QUESTION}, headers=member)
    ).json()
    streamed = await client.post(
        f"{API}/ask/stream", json={"workspace_id": workspace_id, "question": SECRET_QUESTION}, headers=member
    )
    assert streamed.status_code == 200
    await client.post(
        f"{API}/answers/{answer['id']}/feedback", json={"rating": 1, "comment": "tiger-lily-comment"}, headers=member
    )
    await client.post(
        f"{API}/workspaces/{workspace_id}/eval-runs",
        json={"name": "audit", "config": {"retrieval_mode": "hybrid", "rerank": True, "candidate_k": 10, "top_k": 4}},
        headers=admin,
    )
    await client.patch(f"{API}/collections/{collection_id}", json={"name": "Renamed"}, headers=admin)
    assert (await client.delete(f"{API}/documents/{document['id']}", headers=admin)).status_code == 204

    page = await events(client, admin, workspace_id, limit=200)
    by_action: dict[str, list[dict[str, Any]]] = {}
    for item in page["items"]:
        by_action.setdefault(item["action"], []).append(item)
    for expected in (
        audit.WORKSPACE_CREATE, audit.COLLECTION_CREATE, audit.MEMBER_ADD, audit.GROUP_CREATE, audit.GROUP_MEMBER_ADD,
        audit.DOCUMENT_UPLOAD, audit.ASK, audit.FEEDBACK_CREATE, audit.EVAL_RUN, audit.COLLECTION_UPDATE, audit.DOCUMENT_DELETE,
    ):  # fmt: skip
        assert expected in by_action, f"no {expected} entry"
    assert len(by_action[audit.ASK]) == 2  # the plain and the streamed question
    ask_entry = by_action[audit.ASK][0]
    assert ask_entry["actor_email"] == member_email and ask_entry["target"].startswith("answer:")
    assert ask_entry["metadata"]["question_length"] == len(SECRET_QUESTION)
    assert ask_entry["metadata"]["scope"] == "internal" and ask_entry["metadata"]["status"] in ("answered", "refused")
    upload_entry = by_action[audit.DOCUMENT_UPLOAD][0]
    assert upload_entry["metadata"]["bytes"] == len(body) and upload_entry["target"] == f"document:{document['id']}"
    assert by_action[audit.DOCUMENT_DELETE][0]["workspace_id"] == workspace_id  # filed correctly although the row is gone

    async with app.state.sessionmaker() as session:
        everything = json.dumps(
            [dict(r._mapping) for r in await session.execute(text("SELECT * FROM audit_log"))], default=str
        )
    for forbidden in ("zebra-quartz-7731", "unicorn", "forty two", "tiger-lily-comment", "zebra.md"):
        assert forbidden not in everything


async def test_only_workspace_admins_can_read_export_and_verify(client: httpx.AsyncClient) -> None:
    workspace_id, admin, _ = await new_workspace(client)
    member_email, member = await register(client, "plain")
    await add_member(client, admin, workspace_id, member_email)
    _, stranger = await register(client, "stranger")
    for path in ("audit-events", "audit-events/export", "audit-events/verify", "dashboard"):
        url = f"{API}/workspaces/{workspace_id}/{path}"
        assert (await client.get(url, headers=member)).status_code == 403, path
        assert (await client.get(url, headers=stranger)).status_code == 404, path  # existence is not revealed
        assert (await client.get(url)).status_code == 401, path


async def test_one_workspace_never_sees_another_workspaces_entries(client: httpx.AsyncClient) -> None:
    first_ws, first_admin, _ = await new_workspace(client)
    second_ws, second_admin, _ = await new_workspace(client)
    await client.post(f"{API}/workspaces/{first_ws}/groups", json={"name": "only-in-first"}, headers=first_admin)
    first = await events(client, first_admin, first_ws, limit=200)
    second = await events(client, second_admin, second_ws, limit=200)
    assert any(e["action"] == audit.GROUP_CREATE for e in first["items"])
    assert all(e["workspace_id"] in (first_ws, None) for e in first["items"])
    assert all(e["action"] != audit.GROUP_CREATE for e in second["items"])
    first_actor = {e["actor_id"] for e in first["items"]}
    assert not first_actor & {e["actor_id"] for e in second["items"]}  # sign-ins of other people are not shown either


async def test_filters_pagination_and_csv_export(client: httpx.AsyncClient) -> None:
    workspace_id, admin, _ = await new_workspace(client)
    for name in ("g1", "g2", "g3"):
        await client.post(f"{API}/workspaces/{workspace_id}/groups", json={"name": name}, headers=admin)

    only_groups = await events(client, admin, workspace_id, action=audit.GROUP_CREATE)
    assert only_groups["total"] == 3 and {e["action"] for e in only_groups["items"]} == {audit.GROUP_CREATE}
    assert [e["seq"] for e in only_groups["items"]] == sorted((e["seq"] for e in only_groups["items"]), reverse=True)

    first = await events(client, admin, workspace_id, action=audit.GROUP_CREATE, limit=2)
    second = await events(client, admin, workspace_id, action=audit.GROUP_CREATE, limit=2, offset=2)
    assert len(first["items"]) == 2 and len(second["items"]) == 1 and first["total"] == 3
    assert {e["seq"] for e in first["items"]}.isdisjoint(e["seq"] for e in second["items"])

    now = datetime.now(UTC)
    future = await events(client, admin, workspace_id, since=(now + timedelta(hours=1)).isoformat())
    assert future["total"] == 0
    past = await events(client, admin, workspace_id, until=(now - timedelta(hours=1)).isoformat())
    assert past["total"] == 0
    assert (await events(client, admin, workspace_id, actor="no-such-person"))["total"] == 0
    by_id = await events(client, admin, workspace_id, actor=only_groups["items"][0]["actor_id"])
    assert by_id["total"] >= 3
    assert (await client.get(f"{API}/workspaces/{workspace_id}/audit-events?limit=1000", headers=admin)).status_code == 422

    export = await client.get(
        f"{API}/workspaces/{workspace_id}/audit-events/export", params={"action": audit.GROUP_CREATE}, headers=admin
    )
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
    assert "attachment" in export.headers["content-disposition"]
    lines = export.text.strip().split("\n")
    assert lines[0].split(",") == list(audit.CSV_COLUMNS) and len(lines) == 4
    assert audit.AUDIT_EXPORT in [
        e["action"] for e in (await events(client, admin, workspace_id))["items"]
    ]  # exports are logged


async def test_the_chain_verifies_survives_concurrent_writers_and_detects_tampering(
    client: httpx.AsyncClient, app: Any
) -> None:
    workspace_id, admin, _ = await new_workspace(client)
    async with app.state.sessionmaker() as session:
        results = await asyncio.gather(
            *(audit.record(session, None, "test.concurrent", f"n:{i}", None, {"i": i}) for i in range(25))
        )
    assert len(set(results)) == 25  # no two writers got the same position
    report = await verify(client, admin, workspace_id)
    assert report["ok"] is True and report["checked"] >= 25 and report["head_hash"]

    async with app.state.sessionmaker() as session:  # the database itself refuses to rewrite or remove history
        for statement in (
            "UPDATE audit_log SET action = 'x' WHERE seq = 1",
            "DELETE FROM audit_log WHERE seq = 1",
            "TRUNCATE audit_log",
        ):
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(text(statement))
            await session.rollback()

    victim = (report["head_seq"] or 0) - 3
    async with app.state.sessionmaker() as session:
        saved = dict((await session.execute(text("SELECT * FROM audit_log WHERE seq = :s"), {"s": victim})).one()._mapping)
    columns = ", ".join(saved)
    params = ", ".join(f":{c}" for c in saved)
    insert = text(f"INSERT INTO audit_log ({columns}) VALUES ({params})").bindparams(bindparam("metadata", type_=JSONB))
    try:
        async with app.state.sessionmaker() as session:  # an operator with owner rights switches the trigger off and edits
            await session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete"))
            await session.execute(text("UPDATE audit_log SET target = 'tampered' WHERE seq = :s"), {"s": victim})
            await session.commit()
        edited = await verify(client, admin, workspace_id)
        assert edited["ok"] is False and edited["first_bad_seq"] == victim and "changed" in edited["reason"]

        async with app.state.sessionmaker() as session:  # removing an entry is a gap
            await session.execute(text("DELETE FROM audit_log WHERE seq = :s"), {"s": victim})
            await session.commit()
        removed = await verify(client, admin, workspace_id)
        assert removed["ok"] is False and removed["first_bad_seq"] == victim + 1 and "missing" in removed["reason"]
    finally:
        async with app.state.sessionmaker() as session:  # put the row back exactly as it was
            await session.execute(text("DELETE FROM audit_log WHERE seq = :s"), {"s": victim})
            await session.execute(insert, saved)
            await session.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_delete"))
            await session.commit()
    assert (await verify(client, admin, workspace_id))["ok"] is True


async def test_dashboard_numbers_match_what_was_asked(client: httpx.AsyncClient, app: Any) -> None:
    workspace_id, admin, collection_id = await new_workspace(client)
    text_ = "# Lunch Rules\n\n## Hours\n\nLunch is served from noon to one. Please be on time."
    await client.post(
        f"{API}/collections/{collection_id}/documents",
        files={"file": ("lunch.md", text_.encode(), "text/markdown")},
        headers=admin,
    )
    await client.post(
        f"{API}/collections/{collection_id}/documents",
        files={"file": ("broken.pdf", b"%PDF-1.4 not really", "application/pdf")},
        headers=admin,
    )
    await ingest_all(app)

    for question in ("When is lunch served?", "What is the sabbatical policy of the moon base?", "How long is lunch?"):
        answered = await client.post(f"{API}/ask", json={"workspace_id": workspace_id, "question": question}, headers=admin)
        assert answered.status_code == 200
    last = (
        await client.post(
            f"{API}/ask", json={"workspace_id": workspace_id, "question": "Where is the cafeteria?"}, headers=admin
        )
    ).json()
    await client.post(f"{API}/answers/{last['id']}/feedback", json={"rating": 1, "comment": None}, headers=admin)
    await client.post(f"{API}/answers/{last['id']}/feedback", json={"rating": -1, "comment": None}, headers=admin)

    response = await client.get(f"{API}/workspaces/{workspace_id}/dashboard", params={"days": 7}, headers=admin)
    assert response.status_code == 200, response.text
    board = response.json()
    q = board["questions"]
    assert q["total"] == 4 and q["answered"] + q["refused"] == 4
    assert q["refusal_rate"] == pytest.approx(q["refused"] / 4)
    assert 0 <= q["dropped_claim_rate"] <= 1
    assert len(board["per_day"]) == 7 and board["per_day"][-1]["questions"] == 4  # today is last; empty days are zero
    assert sum(d["questions"] for d in board["per_day"]) == 4
    assert board["latency"]["p50_ms"] is not None and board["latency"]["p95_ms"] >= board["latency"]["p50_ms"]
    assert board["cost"]["total_usd"] >= 0 and board["cost"]["per_question_usd"] >= 0
    statuses = {c["label"]: c["count"] for c in board["documents"]["by_status"]}
    assert statuses.get("ready") == 1 and board["documents"]["total"] == sum(statuses.values())
    assert board["documents"]["chunks"] >= 1
    assert board["ingest"]["failed_documents"] == statuses.get("failed", 0)
    assert board["feedback"] == {"up": 1, "down": 1, "positive_ratio": 0.5}
    assert board["egress"] == []  # the internal lane sends nothing out
    serialized = json.dumps(board)
    assert "cafeteria" not in serialized and "sabbatical" not in serialized

    assert (await client.get(f"{API}/workspaces/{workspace_id}/dashboard?days=0", headers=admin)).status_code == 422
    assert (await client.get(f"{API}/workspaces/{workspace_id}/dashboard?days=366", headers=admin)).status_code == 422


async def test_dashboard_counts_egress_by_destination_and_status(client: httpx.AsyncClient, app: Any) -> None:
    workspace_id, admin, _ = await new_workspace(client)
    me = (await client.get(f"{API}/auth/me", headers=admin)).json()
    async with app.state.sessionmaker() as session:
        thread_id = uuid.uuid4()
        await session.execute(
            text("INSERT INTO threads (id, user_id, workspace_id, title) VALUES (:t, :u, :w, 'x')"),
            {"t": thread_id, "u": me["id"], "w": workspace_id},
        )
        for status in ("sent", "sent", "blocked"):
            await session.execute(
                text(
                    "INSERT INTO answers (id, thread_id, user_id, workspace_id, question, answer_json, status, retrieved_chunk_ids,"
                    " config_snapshot, latency_ms_by_stage, tokens_in, tokens_out, cost_usd) VALUES (:id, :t, :u, :w, 'q?', CAST(:aj AS jsonb),"
                    " 'refused', '{}', '{}', CAST(:lat AS jsonb), 10, 5, 0.25)"
                ),
                {
                    "id": uuid.uuid4(), "t": thread_id, "u": me["id"], "w": workspace_id,
                    "aj": json.dumps({"claims": [], "dropped_claims": 2, "egress": [{"destination": "api.openalex.org", "status": status}]}),
                    "lat": json.dumps({"retrieve": 100.0, "generate": 300.0}),
                },
            )  # fmt: skip
        await session.commit()
    board = (await client.get(f"{API}/workspaces/{workspace_id}/dashboard", headers=admin)).json()
    assert {(e["destination"], e["status"]): e["count"] for e in board["egress"]} == {
        ("api.openalex.org", "sent"): 2,
        ("api.openalex.org", "blocked"): 1,
    }
    assert board["latency"]["p50_ms"] == 400.0 and board["latency"]["p95_ms"] == 400.0
    assert board["cost"] == {"total_usd": 0.75, "per_question_usd": 0.25, "tokens_in": 30, "tokens_out": 15}
    assert board["questions"]["claims_dropped"] == 6 and board["questions"]["dropped_claim_rate"] == 1.0
