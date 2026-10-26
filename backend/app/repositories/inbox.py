"""Inbox bookkeeping: what the watcher did with each file, and when it last ran.

`*_for_worker` functions act for the system (the watcher). The API-facing reads always take a workspace id, so a
workspace admin only ever sees rows that belong to their own workspace."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Collection, Document, Workspace
from app.models.annotations import InboxItem, InboxState
from app.models.base import utcnow

# Arbitrary constant: all workers contend for the same lock, so only one scans at a time.
SCAN_LOCK_KEY = 0x4369746553757265


async def try_scan_lock(session: AsyncSession) -> bool:
    """A transaction-scoped advisory lock: released when the session's transaction ends, even if the worker dies."""
    return bool((await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": SCAN_LOCK_KEY})).scalar())


async def workspaces_for_worker(session: AsyncSession) -> list[tuple[uuid.UUID, str]]:
    rows = (await session.execute(select(Workspace.id, Workspace.name).order_by(Workspace.created_at))).all()
    return [(i, n) for i, n in rows]


async def collections_in(session: AsyncSession, workspace_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    stmt = select(Collection.id, Collection.name).where(Collection.workspace_id == workspace_id).order_by(Collection.name)
    return [(i, n) for i, n in (await session.execute(stmt)).all()]


async def already_handled(session: AsyncSession, source_key: str, size_bytes: int, mtime_ns: int) -> bool:
    stmt = select(InboxItem.id).where(
        InboxItem.source_key == source_key, InboxItem.size_bytes == size_bytes, InboxItem.mtime_ns == mtime_ns
    )
    return (await session.execute(stmt.limit(1))).first() is not None


def new_item(
    *,
    workspace_id: uuid.UUID | None,
    collection_id: uuid.UUID | None,
    source_key: str,
    folder: str,
    filename: str,
    size_bytes: int,
    mtime_ns: int,
    status: str,
    reason: str | None = None,
    sha256: str | None = None,
    document_id: uuid.UUID | None = None,
) -> InboxItem:
    return InboxItem(
        workspace_id=workspace_id,
        collection_id=collection_id,
        document_id=document_id,
        source_key=source_key[:1000],
        folder=folder[:600],
        filename=filename[:300],
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        sha256=sha256,
        status=status,
        reason=reason,
    )


async def list_items(
    session: AsyncSession, workspace_id: uuid.UUID, *, status: str | None, limit: int
) -> list[tuple[InboxItem, str | None, str | None]]:
    """(item, collection name, document status), newest first."""
    stmt = (
        select(InboxItem, Collection.name, Document.status)
        .outerjoin(Collection, Collection.id == InboxItem.collection_id)
        .outerjoin(Document, Document.id == InboxItem.document_id)
        .where(InboxItem.workspace_id == workspace_id)
        .order_by(InboxItem.created_at.desc())
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(InboxItem.status == status)
    return [(i, c, d) for i, c, d in (await session.execute(stmt)).all()]


async def status_counts(
    session: AsyncSession, workspace_id: uuid.UUID
) -> list[tuple[uuid.UUID | None, str, str, int, datetime | None]]:
    """(collection_id, folder, status, count, latest) grouped; unmatched files group by their folder instead."""
    stmt = (
        select(InboxItem.collection_id, InboxItem.folder, InboxItem.status, func.count(), func.max(InboxItem.created_at))
        .where(InboxItem.workspace_id == workspace_id)
        .group_by(InboxItem.collection_id, InboxItem.folder, InboxItem.status)
    )
    return [(c, f, s, n, m) for c, f, s, n, m in (await session.execute(stmt)).all()]


async def get_state(session: AsyncSession) -> InboxState | None:
    return await session.get(InboxState, 1)


async def request_scan(session: AsyncSession) -> None:
    stmt = pg_insert(InboxState).values(id=1, scan_requested_at=utcnow(), last_counts={})
    stmt = stmt.on_conflict_do_update(index_elements=[InboxState.id], set_={"scan_requested_at": utcnow()})
    await session.execute(stmt)


async def finish_scan(session: AsyncSession, started_requested_at: datetime | None, counts: dict[str, Any]) -> None:
    """Record the scan. A request that arrived while it ran (newer than what the scan started with) stays pending."""
    now = utcnow()
    stmt = pg_insert(InboxState).values(id=1, last_scan_at=now, last_counts=counts)
    await session.execute(
        stmt.on_conflict_do_update(index_elements=[InboxState.id], set_={"last_scan_at": now, "last_counts": counts})
    )
    if started_requested_at is not None:
        await session.execute(
            update(InboxState)
            .where(InboxState.id == 1, InboxState.scan_requested_at <= started_requested_at)
            .values(scan_requested_at=None)
        )
