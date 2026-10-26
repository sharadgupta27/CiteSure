"""Database access for the full-text cache and its requests. No document text and no user text is stored here: papers
are public, and a request holds only the paper's address and status."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, literal_column, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.fulltext import FullTextChunk, FullTextPaper, FullTextRequest
from app.rag.retrieval.fulltext import chunk_id_for

IN_FLIGHT_MINUTES = 15  # a queued or running request younger than this is shared instead of duplicated


async def lock_workspace_budget(session: AsyncSession, workspace_id: uuid.UUID) -> None:
    """Serialise budget checks for one workspace until the transaction ends, so two clicks cannot both pass."""
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"fulltext:{workspace_id}"})


async def downloads_today(session: AsyncSession, workspace_id: uuid.UUID, since: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(FullTextRequest)
        .where(
            FullTextRequest.workspace_id == workspace_id,
            FullTextRequest.counted.is_(True),
            FullTextRequest.created_at >= since,
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def fresh_paper(session: AsyncSession, paper_key: str) -> FullTextPaper | None:
    stmt = select(FullTextPaper).where(FullTextPaper.paper_key == paper_key, FullTextPaper.expires_at > func.now())
    return (await session.execute(stmt)).scalar_one_or_none()


async def in_flight(session: AsyncSession, workspace_id: uuid.UUID, paper_key: str) -> FullTextRequest | None:
    cutoff = utcnow() - timedelta(minutes=IN_FLIGHT_MINUTES)
    stmt = (
        select(FullTextRequest)
        .where(
            FullTextRequest.workspace_id == workspace_id,
            FullTextRequest.paper_key == paper_key,
            FullTextRequest.status.in_(["queued", "running"]),
            FullTextRequest.created_at >= cutoff,
        )
        .order_by(FullTextRequest.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_request(session: AsyncSession, **values: Any) -> FullTextRequest:
    row = FullTextRequest(**values)
    session.add(row)
    await session.flush()
    return row


async def get_request(session: AsyncSession, request_id: uuid.UUID) -> FullTextRequest | None:
    return await session.get(FullTextRequest, request_id)


async def replace_paper(
    session: AsyncSession, paper: dict[str, Any], rows: Sequence[dict[str, Any]], *, ttl_days: int
) -> FullTextPaper:
    """Store one paper and all its passages in the caller's transaction; an older copy (expired, or refetched) is
    removed first, so a half-indexed paper is never visible."""
    # Two workspaces may add the same paper at once: the second waits here, then replaces the first's copy.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"fulltext-paper:{paper['paper_key']}"}
    )
    await purge_expired(session)
    await session.execute(delete(FullTextPaper).where(FullTextPaper.paper_key == paper["paper_key"]))
    now = utcnow()
    row = FullTextPaper(**paper, fetched_at=now, expires_at=now + timedelta(days=ttl_days))
    session.add(row)
    await session.flush()
    for values in rows:
        session.add(
            FullTextChunk(
                id=chunk_id_for(row.id, values["ord"]),
                paper_id=row.id,
                # computed by Postgres so the text-search configuration lives in one place (the database)
                tsv=func.to_tsvector(literal_column("'english'::regconfig"), values["fts_text"]),
                **{k: v for k, v in values.items() if k != "fts_text"},
            )
        )
    await session.flush()
    return row


async def purge_expired(session: AsyncSession) -> int:
    result = await session.execute(delete(FullTextPaper).where(FullTextPaper.expires_at <= func.now()))
    return int(getattr(result, "rowcount", 0) or 0)


async def update_request(session: AsyncSession, request_id: uuid.UUID, **values: Any) -> None:
    await session.execute(update(FullTextRequest).where(FullTextRequest.id == request_id).values(**values))
