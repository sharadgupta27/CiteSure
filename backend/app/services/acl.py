"""Access control. This module is the ONLY place that decides who may read what (non-negotiable 1).

Rules:
- A workspace *admin* may read every collection in that workspace.
- A workspace *member* may read collections with visibility `workspace`, and collections with visibility
  `groups` when the member belongs to at least one of the listed groups.
- Everyone else (including non-members) can read nothing, and gets 404 rather than 403 so the existence of a
  workspace or document is not revealed.

Every query that returns document or chunk content must be filtered with the ids returned here, inside the SQL
(WHERE collection_id IN ...), never after the rows have been fetched.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import Forbidden, NotFound
from app.repositories import collections as collections_repo
from app.repositories import workspaces as workspaces_repo


@dataclass(frozen=True)
class CollectionAccessRow:
    collection_id: uuid.UUID
    workspace_id: uuid.UUID
    visibility: str
    group_ids: frozenset[uuid.UUID]


@dataclass(frozen=True)
class AccessContext:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: str
    allowed_collection_ids: tuple[uuid.UUID, ...]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def resolve_allowed(
    memberships: dict[uuid.UUID, str], user_group_ids: set[uuid.UUID], rows: Sequence[CollectionAccessRow]
) -> list[uuid.UUID]:
    """Pure decision function (unit-tested exhaustively). `memberships` maps workspace id to role."""
    allowed: list[uuid.UUID] = []
    for row in rows:
        role = memberships.get(row.workspace_id)
        if role is None:
            continue
        if role == "admin" or row.visibility == "workspace" or (row.group_ids & user_group_ids):
            allowed.append(row.collection_id)
    return allowed


async def allowed_collection_ids(
    session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID | None = None
) -> list[uuid.UUID]:
    """Collection ids the user may read, across all their workspaces or in one workspace."""
    memberships = await workspaces_repo.memberships_for_user(session, user_id, workspace_id)
    if not memberships:
        return []
    group_ids = await workspaces_repo.all_group_ids_for_user(session, user_id)
    rows = [
        CollectionAccessRow(cid, wid, visibility, groups)
        for cid, wid, visibility, groups in await collections_repo.access_rows(session, list(memberships))
    ]
    return resolve_allowed(memberships, group_ids, rows)


async def context_for_workspace(session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID) -> AccessContext:
    role = await workspaces_repo.get_role(session, user_id, workspace_id)
    if role is None:
        raise NotFound("Workspace not found")
    allowed = await allowed_collection_ids(session, user_id, workspace_id)
    return AccessContext(user_id, workspace_id, role, tuple(allowed))


async def require_admin(session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID) -> AccessContext:
    context = await context_for_workspace(session, user_id, workspace_id)
    if not context.is_admin:
        raise Forbidden("Only workspace admins can do this")
    return context
