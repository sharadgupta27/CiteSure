"""Reading the audit log (writing is `services/audit.py`: it needs the chain lock)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Membership
from app.models.security import AuditEvent


def _scoped(
    workspace_id: uuid.UUID,
    *,
    actor: str | None,
    action: str | None,
    since: datetime | None,
    until: datetime | None,
) -> Select[Any]:
    """Events of one workspace, plus workspace-less ones (sign-ins) made by its members. Another workspace's events
    and sign-ins of people outside this workspace are never included."""
    members = select(Membership.user_id).where(Membership.workspace_id == workspace_id)
    stmt = select(AuditEvent).where(
        or_(AuditEvent.workspace_id == workspace_id, (AuditEvent.workspace_id.is_(None)) & AuditEvent.actor_id.in_(members))
    )
    if actor:
        try:
            stmt = stmt.where(AuditEvent.actor_id == uuid.UUID(actor))
        except ValueError:
            escaped = actor.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
            stmt = stmt.where(AuditEvent.actor_email.ilike(f"%{escaped}%", escape="\\"))
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if since:
        stmt = stmt.where(AuditEvent.created_at >= since)
    if until:
        stmt = stmt.where(AuditEvent.created_at < until)
    return stmt


async def list_events(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    actor: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[AuditEvent], int]:
    base = _scoped(workspace_id, actor=actor, action=action, since=since, until=until)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await session.execute(base.order_by(AuditEvent.seq.desc()).limit(limit).offset(offset))).scalars().all()
    return rows, int(total)
