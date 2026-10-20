"""Postgres-backed job queue: `FOR UPDATE SKIP LOCKED` lets many workers pull jobs without Redis."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


async def enqueue(session: AsyncSession, kind: str, payload: dict[str, Any], *, max_attempts: int = 3) -> uuid.UUID:
    job = Job(kind=kind, payload=payload, max_attempts=max_attempts)
    session.add(job)
    await session.flush()
    return job.id


_CLAIM = text(
    """
    UPDATE jobs SET status = 'running', locked_at = now(), attempts = attempts + 1
    WHERE id = (
        SELECT id FROM jobs
        WHERE (status = 'queued' AND run_after <= now())
           OR (status = 'running' AND locked_at < now() - interval '15 minutes')
        ORDER BY run_after
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, kind, payload, attempts, max_attempts
    """
)


async def claim_next(session: AsyncSession) -> ClaimedJob | None:
    row = (await session.execute(_CLAIM)).first()
    if row is None:
        return None
    return ClaimedJob(row.id, row.kind, row.payload, row.attempts, row.max_attempts)


async def mark_done(session: AsyncSession, job_id: uuid.UUID) -> None:
    await session.execute(
        text("UPDATE jobs SET status = 'done', locked_at = NULL, error = NULL WHERE id = :id"), {"id": job_id}
    )


async def mark_failed(session: AsyncSession, job: ClaimedJob, error: str) -> bool:
    """Retry with exponential backoff until max_attempts, then fail for good. Returns True if it will retry."""
    retry = job.attempts < job.max_attempts
    await session.execute(
        text(
            """
            UPDATE jobs SET status = :status, locked_at = NULL, error = :error,
                run_after = now() + make_interval(secs => :delay)
            WHERE id = :id
            """
        ),
        {
            "id": job.id,
            "status": "queued" if retry else "failed",
            "error": error[:2000],
            "delay": float(5 * 2**job.attempts) if retry else 0.0,
        },
    )
    return retry


async def queue_depth(session: AsyncSession) -> int:
    stmt = select(func.count()).select_from(Job).where(Job.status.in_(["queued", "running"]))
    return int((await session.execute(stmt)).scalar_one())
