"""Reading progress. Every row is keyed by (user, document), and every read takes the user id: nobody sees anyone
else's progress. Listings join `documents` and filter by the caller's readable collections in SQL, so progress on a
document the user can no longer read disappears from view with the access."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.models.learning import ReadingProgress


async def get(session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID) -> ReadingProgress | None:
    stmt = select(ReadingProgress).where(ReadingProgress.user_id == user_id, ReadingProgress.document_id == document_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_for_update(
    session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID, now: datetime
) -> ReadingProgress:
    """The row, created empty when missing, locked until commit so two tabs cannot lose each other's pages."""
    await session.execute(
        pg_insert(ReadingProgress)
        .values(
            user_id=user_id,
            document_id=document_id,
            last_page=None,
            pages_read=[],
            percent=0.0,
            last_opened_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "document_id"])
    )
    stmt = (
        select(ReadingProgress)
        .where(ReadingProgress.user_id == user_id, ReadingProgress.document_id == document_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one()


async def delete_for(session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID) -> None:
    await session.execute(
        delete(ReadingProgress).where(ReadingProgress.user_id == user_id, ReadingProgress.document_id == document_id)
    )


async def list_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, allowed_collection_ids: Sequence[uuid.UUID], limit: int = 100
) -> list[tuple[ReadingProgress, Document]]:
    stmt = (
        select(ReadingProgress, Document)
        .join(Document, Document.id == ReadingProgress.document_id)
        .where(ReadingProgress.user_id == user_id, Document.collection_id.in_(allowed_collection_ids))
        .order_by(ReadingProgress.last_opened_at.desc())
        .limit(limit)
    )
    return [(p, d) for p, d in (await session.execute(stmt)).all()]


async def for_documents(
    session: AsyncSession, user_id: uuid.UUID, document_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, ReadingProgress]:
    """Progress rows of this user for these documents. Callers pass ids they already checked against the ACL."""
    if not document_ids:
        return {}
    stmt = select(ReadingProgress).where(ReadingProgress.user_id == user_id, ReadingProgress.document_id.in_(document_ids))
    return {p.document_id: p for p in (await session.execute(stmt)).scalars().all()}
