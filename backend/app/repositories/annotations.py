"""Annotations. Every read and write is scoped to the author (`user_id`): there is no query that returns another user's
rows. Whether the author may still read the document is the service's check (services/acl.py)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.annotations import Annotation
from app.models.base import utcnow


async def list_for_document(session: AsyncSession, document_id: uuid.UUID, user_id: uuid.UUID) -> list[Annotation]:
    stmt = (
        select(Annotation)
        .where(Annotation.document_id == document_id, Annotation.user_id == user_id)
        .order_by(Annotation.page, Annotation.created_at)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_owned(session: AsyncSession, annotation_id: uuid.UUID, user_id: uuid.UUID) -> Annotation | None:
    stmt = select(Annotation).where(Annotation.id == annotation_id, Annotation.user_id == user_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    page: int,
    rects: list[dict[str, Any]],
    text: str,
    note: str,
    color: str,
) -> Annotation:
    row = Annotation(document_id=document_id, user_id=user_id, page=page, rects=rects, text=text, note=note, color=color)
    session.add(row)
    await session.flush()
    return row


async def update(session: AsyncSession, row: Annotation, *, note: str | None, color: str | None) -> Annotation:
    if note is not None:
        row.note = note
    if color is not None:
        row.color = color
    row.updated_at = utcnow()
    await session.flush()
    return row


async def delete_row(session: AsyncSession, annotation_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await session.execute(delete(Annotation).where(Annotation.id == annotation_id, Annotation.user_id == user_id))
