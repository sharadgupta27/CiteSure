"""Aggregates for the admin dashboard. Counts and percentiles only: no question or document text is selected, and the
queries that touch documents and chunks are limited to the collections the admin may read (non-negotiable 1)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

_IDS = PG_ARRAY(PGUUID(as_uuid=True))


async def question_days(session: AsyncSession, workspace_id: uuid.UUID, since: datetime) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
                   count(*) AS questions,
                   count(*) FILTER (WHERE status = 'answered') AS answered,
                   count(*) FILTER (WHERE status = 'refused') AS refused,
                   coalesce(sum(cost_usd), 0) AS cost_usd
            FROM answers WHERE workspace_id = :ws AND created_at >= :since
            GROUP BY 1 ORDER BY 1
            """
        ),
        {"ws": workspace_id, "since": since},
    )
    return [dict(r._mapping) for r in rows]


async def question_totals(session: AsyncSession, workspace_id: uuid.UUID, since: datetime) -> dict[str, Any]:
    row = await session.execute(
        text(
            """
            SELECT coalesce(sum(tokens_in), 0) AS tokens_in,
                   coalesce(sum(tokens_out), 0) AS tokens_out,
                   coalesce(sum((answer_json->>'dropped_claims')::int), 0) AS claims_dropped,
                   coalesce(sum(jsonb_array_length(coalesce(answer_json->'claims', '[]'::jsonb))), 0) AS claims_shown
            FROM answers WHERE workspace_id = :ws AND created_at >= :since
            """
        ),
        {"ws": workspace_id, "since": since},
    )
    return dict(row.one()._mapping)


async def latency_percentiles(
    session: AsyncSession, workspace_id: uuid.UUID, since: datetime
) -> tuple[float | None, float | None]:
    """End-to-end time of an answer = the sum of its stage timings."""
    row = (
        await session.execute(
            text(
                """
                SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY t.total) AS p50,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY t.total) AS p95
                FROM answers a
                CROSS JOIN LATERAL (
                    SELECT coalesce(sum(value::float), 0) AS total FROM jsonb_each_text(a.latency_ms_by_stage)
                ) t
                WHERE a.workspace_id = :ws AND a.created_at >= :since
                """
            ),
            {"ws": workspace_id, "since": since},
        )
    ).one()
    return (None if row.p50 is None else float(row.p50)), (None if row.p95 is None else float(row.p95))


async def egress_counts(session: AsyncSession, workspace_id: uuid.UUID, since: datetime) -> list[tuple[str, str, int]]:
    rows = await session.execute(
        text(
            """
            SELECT e->>'destination' AS destination, e->>'status' AS status, count(*) AS n
            FROM answers a
            CROSS JOIN LATERAL jsonb_array_elements(coalesce(a.answer_json->'egress', '[]'::jsonb)) e
            WHERE a.workspace_id = :ws AND a.created_at >= :since
            GROUP BY 1, 2 ORDER BY n DESC, 1, 2
            """
        ),
        {"ws": workspace_id, "since": since},
    )
    return [(r.destination or "unknown", r.status or "unknown", int(r.n)) for r in rows]


async def feedback_counts(session: AsyncSession, workspace_id: uuid.UUID, since: datetime) -> tuple[int, int]:
    row = (
        await session.execute(
            text(
                """
                SELECT count(*) FILTER (WHERE f.rating = 1) AS up, count(*) FILTER (WHERE f.rating = -1) AS down
                FROM feedback f JOIN answers a ON a.id = f.answer_id
                WHERE a.workspace_id = :ws AND f.created_at >= :since
                """
            ),
            {"ws": workspace_id, "since": since},
        )
    ).one()
    return int(row.up), int(row.down)


async def document_status_counts(session: AsyncSession, collection_ids: Sequence[uuid.UUID]) -> list[tuple[str, int]]:
    stmt = text(
        "SELECT status, count(*) AS n FROM documents WHERE collection_id = ANY(:ids) GROUP BY status ORDER BY status"
    )
    rows = await session.execute(stmt.bindparams(bindparam("ids", list(collection_ids), type_=_IDS)))
    return [(r.status, int(r.n)) for r in rows]


async def chunk_count(session: AsyncSession, collection_ids: Sequence[uuid.UUID]) -> int:
    stmt = text("SELECT count(*) FROM chunks WHERE collection_id = ANY(:ids)")
    return int((await session.execute(stmt.bindparams(bindparam("ids", list(collection_ids), type_=_IDS)))).scalar_one())


async def failed_ingest_jobs(session: AsyncSession, collection_ids: Sequence[uuid.UUID], since: datetime) -> int:
    stmt = text(
        """
        SELECT count(*) FROM jobs j JOIN documents d ON d.id::text = j.payload->>'document_id'
        WHERE j.kind = 'ingest_document' AND j.status = 'failed' AND j.created_at >= :since AND d.collection_id = ANY(:ids)
        """
    )
    stmt = stmt.bindparams(bindparam("ids", list(collection_ids), type_=_IDS), bindparam("since", since))
    return int((await session.execute(stmt)).scalar_one())


async def recent_failed_documents(
    session: AsyncSession, collection_ids: Sequence[uuid.UUID], limit: int = 10
) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT id, title, left(error, 200) AS error, created_at FROM documents
        WHERE status = 'failed' AND collection_id = ANY(:ids) ORDER BY created_at DESC LIMIT :limit
        """
    )
    stmt = stmt.bindparams(bindparam("ids", list(collection_ids), type_=_IDS), bindparam("limit", limit))
    return [dict(r._mapping) for r in await session.execute(stmt)]
