from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SYSTEM_EMAIL_DOMAIN
from app.models import Group, GroupMember, Membership, User, Workspace


async def create_workspace(session: AsyncSession, name: str) -> Workspace:
    ws = Workspace(name=name)
    session.add(ws)
    await session.flush()
    return ws


async def add_membership(session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID, role: str) -> None:
    session.add(Membership(user_id=user_id, workspace_id=workspace_id, role=role))
    await session.flush()


async def get_role(session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID) -> str | None:
    stmt = select(Membership.role).where(Membership.user_id == user_id, Membership.workspace_id == workspace_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_for_user(session: AsyncSession, user_id: uuid.UUID) -> Sequence[tuple[Workspace, str]]:
    stmt = (
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user_id)
        .order_by(Workspace.created_at)
    )
    return [(w, r) for w, r in (await session.execute(stmt)).all()]


async def list_members(session: AsyncSession, workspace_id: uuid.UUID) -> Sequence[tuple[uuid.UUID, str, str]]:
    stmt = (
        select(User.id, User.email, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == workspace_id, ~User.email.endswith("@" + SYSTEM_EMAIL_DOMAIN))
        .order_by(User.email)
    )
    return [(i, e, r) for i, e, r in (await session.execute(stmt)).all()]


async def create_group(session: AsyncSession, workspace_id: uuid.UUID, name: str) -> Group:
    group = Group(workspace_id=workspace_id, name=name)
    session.add(group)
    await session.flush()
    return group


async def get_group(session: AsyncSession, group_id: uuid.UUID) -> Group | None:
    return await session.get(Group, group_id)


async def group_by_name(session: AsyncSession, workspace_id: uuid.UUID, name: str) -> Group | None:
    stmt = select(Group).where(Group.workspace_id == workspace_id, Group.name == name)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_groups(session: AsyncSession, workspace_id: uuid.UUID) -> Sequence[tuple[Group, list[uuid.UUID]]]:
    groups = (
        (await session.execute(select(Group).where(Group.workspace_id == workspace_id).order_by(Group.name))).scalars().all()
    )
    if not groups:
        return []
    rows = (
        await session.execute(
            select(GroupMember.group_id, GroupMember.user_id)
            .join(User, User.id == GroupMember.user_id)
            .where(
                GroupMember.group_id.in_([g.id for g in groups]),
                ~User.email.endswith("@" + SYSTEM_EMAIL_DOMAIN),  # hide the evaluator's synthetic users
            )
        )
    ).all()
    members: dict[uuid.UUID, list[uuid.UUID]] = {g.id: [] for g in groups}
    for group_id, user_id in rows:
        members[group_id].append(user_id)
    return [(g, members[g.id]) for g in groups]


async def group_member_ids(session: AsyncSession, group_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = select(GroupMember.user_id).where(GroupMember.group_id == group_id)
    return list((await session.execute(stmt)).scalars().all())


async def add_group_member(session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID) -> None:
    existing = await session.get(GroupMember, (group_id, user_id))
    if existing is None:
        session.add(GroupMember(group_id=group_id, user_id=user_id))
        await session.flush()


async def group_ids_for_user(session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID) -> set[uuid.UUID]:
    stmt = (
        select(GroupMember.group_id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.user_id == user_id, Group.workspace_id == workspace_id)
    )
    return set((await session.execute(stmt)).scalars().all())


async def memberships_for_user(
    session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID | None = None
) -> dict[uuid.UUID, str]:
    stmt = select(Membership.workspace_id, Membership.role).where(Membership.user_id == user_id)
    if workspace_id is not None:
        stmt = stmt.where(Membership.workspace_id == workspace_id)
    return {ws: role for ws, role in (await session.execute(stmt)).all()}


async def all_group_ids_for_user(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    stmt = select(GroupMember.group_id).where(GroupMember.user_id == user_id)
    return set((await session.execute(stmt)).scalars().all())
