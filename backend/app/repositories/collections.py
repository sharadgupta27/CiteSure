from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Collection, CollectionGroup, Document


async def create(session: AsyncSession, workspace_id: uuid.UUID, name: str, visibility: str) -> Collection:
    collection = Collection(workspace_id=workspace_id, name=name, visibility=visibility)
    session.add(collection)
    await session.flush()
    return collection


async def get(session: AsyncSession, collection_id: uuid.UUID) -> Collection | None:
    return await session.get(Collection, collection_id)


async def by_name(session: AsyncSession, workspace_id: uuid.UUID, name: str) -> Collection | None:
    stmt = select(Collection).where(Collection.workspace_id == workspace_id, Collection.name == name)
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_groups(session: AsyncSession, collection_id: uuid.UUID, group_ids: Sequence[uuid.UUID]) -> None:
    await session.execute(delete(CollectionGroup).where(CollectionGroup.collection_id == collection_id))
    for group_id in dict.fromkeys(group_ids):
        session.add(CollectionGroup(collection_id=collection_id, group_id=group_id))
    await session.flush()


async def group_ids(session: AsyncSession, collection_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = select(CollectionGroup.group_id).where(CollectionGroup.collection_id == collection_id)
    return list((await session.execute(stmt)).scalars().all())


async def list_with_groups(session: AsyncSession, workspace_id: uuid.UUID) -> Sequence[tuple[Collection, list[uuid.UUID]]]:
    collections = (
        (await session.execute(select(Collection).where(Collection.workspace_id == workspace_id).order_by(Collection.name)))
        .scalars()
        .all()
    )
    if not collections:
        return []
    rows = (
        await session.execute(
            select(CollectionGroup.collection_id, CollectionGroup.group_id).where(
                CollectionGroup.collection_id.in_([c.id for c in collections])
            )
        )
    ).all()
    groups: dict[uuid.UUID, list[uuid.UUID]] = {c.id: [] for c in collections}
    for collection_id, group_id in rows:
        groups[collection_id].append(group_id)
    return [(c, groups[c.id]) for c in collections]


async def blob_keys(session: AsyncSession, collection_id: uuid.UUID) -> list[str]:
    stmt = select(Document.blob_key).where(Document.collection_id == collection_id)
    return list((await session.execute(stmt)).scalars().all())


async def delete_collection(session: AsyncSession, collection_id: uuid.UUID) -> None:
    await session.execute(delete(Collection).where(Collection.id == collection_id))


async def access_rows(
    session: AsyncSession, workspace_ids: Sequence[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID, str, frozenset[uuid.UUID]]]:
    """(collection_id, workspace_id, visibility, group_ids) for every collection in the given workspaces."""
    if not workspace_ids:
        return []
    collections = (
        await session.execute(
            select(Collection.id, Collection.workspace_id, Collection.visibility).where(
                Collection.workspace_id.in_(workspace_ids)
            )
        )
    ).all()
    group_rows = (
        await session.execute(
            select(CollectionGroup.collection_id, CollectionGroup.group_id).where(
                CollectionGroup.collection_id.in_([c.id for c in collections])
            )
        )
    ).all()
    groups: dict[uuid.UUID, set[uuid.UUID]] = {}
    for collection_id, group_id in group_rows:
        groups.setdefault(collection_id, set()).add(group_id)
    return [(c.id, c.workspace_id, c.visibility, frozenset(groups.get(c.id, set()))) for c in collections]
