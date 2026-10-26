"""Study sets and their items. Sets are private to their owner: every lookup takes the user id.

Items that point at a document are returned only while the document is inside `allowed_collection_ids` (decided in
SQL by the join), so a revoked document silently drops out of the set instead of leaking its title."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.models.base import utcnow
from app.models.learning import StudySet, StudySetItem


async def create_set(
    session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID, name: str, description: str
) -> StudySet:
    row = StudySet(user_id=user_id, workspace_id=workspace_id, name=name, description=description, notes="")
    session.add(row)
    await session.flush()
    return row


async def name_taken(
    session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID, name: str, *, except_id: uuid.UUID | None = None
) -> bool:
    stmt = select(StudySet.id).where(
        StudySet.user_id == user_id, StudySet.workspace_id == workspace_id, StudySet.name == name
    )
    if except_id is not None:
        stmt = stmt.where(StudySet.id != except_id)
    return (await session.execute(stmt)).first() is not None


async def get_set(session: AsyncSession, set_id: uuid.UUID, user_id: uuid.UUID) -> StudySet | None:
    stmt = select(StudySet).where(StudySet.id == set_id, StudySet.user_id == user_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_sets(session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID) -> Sequence[StudySet]:
    stmt = (
        select(StudySet)
        .where(StudySet.user_id == user_id, StudySet.workspace_id == workspace_id)
        .order_by(StudySet.updated_at.desc(), StudySet.name)
    )
    return (await session.execute(stmt)).scalars().all()


async def delete_set(session: AsyncSession, set_id: uuid.UUID) -> None:
    await session.execute(delete(StudySet).where(StudySet.id == set_id))


async def touch(session: AsyncSession, set_id: uuid.UUID) -> None:
    await session.execute(update(StudySet).where(StudySet.id == set_id).values(updated_at=utcnow()))


async def visible_items(
    session: AsyncSession, set_ids: Sequence[uuid.UUID], *, allowed_collection_ids: Sequence[uuid.UUID]
) -> list[tuple[StudySetItem, Document | None]]:
    """Items of these sets in order: references always, documents only when the caller may read them."""
    if not set_ids:
        return []
    stmt = (
        select(StudySetItem, Document)
        .outerjoin(Document, Document.id == StudySetItem.document_id)
        .where(
            StudySetItem.study_set_id.in_(set_ids),
            (StudySetItem.kind == "reference") | Document.collection_id.in_(allowed_collection_ids),
        )
        .order_by(StudySetItem.study_set_id, StudySetItem.position, StudySetItem.added_at)
    )
    return [(i, d) for i, d in (await session.execute(stmt)).all()]


async def get_item(session: AsyncSession, set_id: uuid.UUID, item_id: uuid.UUID) -> StudySetItem | None:
    stmt = select(StudySetItem).where(StudySetItem.id == item_id, StudySetItem.study_set_id == set_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def item_exists_for_document(session: AsyncSession, set_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    stmt = select(StudySetItem.id).where(StudySetItem.study_set_id == set_id, StudySetItem.document_id == document_id)
    return (await session.execute(stmt)).first() is not None


async def all_items(session: AsyncSession, set_id: uuid.UUID) -> list[StudySetItem]:
    stmt = (
        select(StudySetItem)
        .where(StudySetItem.study_set_id == set_id)
        .order_by(StudySetItem.position, StudySetItem.added_at)
    )
    return list((await session.execute(stmt)).scalars().all())


async def next_position(session: AsyncSession, set_id: uuid.UUID) -> int:
    top = (
        await session.execute(select(func.max(StudySetItem.position)).where(StudySetItem.study_set_id == set_id))
    ).scalar()
    return 0 if top is None else top + 1


async def add_item(
    session: AsyncSession,
    set_id: uuid.UUID,
    *,
    kind: str,
    document_id: uuid.UUID | None,
    ref_title: str | None,
    ref_url: str | None,
    ref_source: str | None,
    note: str,
) -> StudySetItem:
    row = StudySetItem(
        study_set_id=set_id,
        position=await next_position(session, set_id),
        kind=kind,
        document_id=document_id,
        ref_title=ref_title,
        ref_url=ref_url,
        ref_source=ref_source,
        note=note,
    )
    session.add(row)
    await session.flush()
    return row


async def delete_item(session: AsyncSession, item_id: uuid.UUID) -> None:
    await session.execute(delete(StudySetItem).where(StudySetItem.id == item_id))
