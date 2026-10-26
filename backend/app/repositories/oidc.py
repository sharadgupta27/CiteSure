"""OIDC identities and the group memberships the identity provider granted."""

from __future__ import annotations

import uuid
from collections.abc import Collection

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, GroupMember, Membership
from app.models.base import utcnow
from app.models.security import OidcGroupGrant, OidcIdentity


async def get_identity(session: AsyncSession, issuer: str, subject: str) -> OidcIdentity | None:
    stmt = select(OidcIdentity).where(OidcIdentity.issuer == issuer, OidcIdentity.subject == subject)
    return (await session.execute(stmt)).scalar_one_or_none()


async def add_identity(session: AsyncSession, user_id: uuid.UUID, issuer: str, subject: str) -> OidcIdentity:
    identity = OidcIdentity(user_id=user_id, issuer=issuer, subject=subject)
    session.add(identity)
    await session.flush()
    return identity


def touch(identity: OidcIdentity) -> None:
    identity.last_login_at = utcnow()


async def groups_named(session: AsyncSession, user_id: uuid.UUID, names: Collection[str]) -> list[Group]:
    """Existing groups with one of these names, in workspaces the user already belongs to. Nothing is ever created."""
    if not names:
        return []
    stmt = (
        select(Group)
        .join(Membership, Membership.workspace_id == Group.workspace_id)
        .where(Membership.user_id == user_id, Group.name.in_(list(names)))
    )
    return list((await session.execute(stmt)).scalars().all())


async def granted_group_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    stmt = select(OidcGroupGrant.group_id).where(OidcGroupGrant.user_id == user_id)
    return set((await session.execute(stmt)).scalars().all())


async def grant(session: AsyncSession, user_id: uuid.UUID, group_id: uuid.UUID) -> bool:
    """Add the membership if it is missing and remember that the provider granted it. A membership an admin added by
    hand is left alone (and is never revoked by a login). Returns True when something was added."""
    if await session.get(GroupMember, (group_id, user_id)) is not None:
        return False
    session.add(GroupMember(group_id=group_id, user_id=user_id))
    session.add(OidcGroupGrant(user_id=user_id, group_id=group_id))
    await session.flush()
    return True


async def revoke(session: AsyncSession, user_id: uuid.UUID, group_ids: Collection[uuid.UUID]) -> None:
    if not group_ids:
        return
    ids = list(group_ids)
    await session.execute(delete(GroupMember).where(GroupMember.user_id == user_id, GroupMember.group_id.in_(ids)))
    await session.execute(delete(OidcGroupGrant).where(OidcGroupGrant.user_id == user_id, OidcGroupGrant.group_id.in_(ids)))
