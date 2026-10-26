"""Admin reads of the audit log: filtered pages, CSV export and the chain check. Workspace admins only."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import AuditEvent
from app.repositories import audit as audit_repo
from app.schemas import admin as a
from app.services import acl
from app.services import audit as audit_service

EXPORT_LIMIT = 50_000


class AuditAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_events(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        actor: str | None,
        action: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        offset: int,
    ) -> a.AuditEventPage:
        await acl.require_admin(self.session, user_id, workspace_id)
        rows, total = await audit_repo.list_events(
            self.session, workspace_id, actor=actor, action=action, since=since, until=until, limit=limit, offset=offset
        )
        return a.AuditEventPage(items=[_to_event(r) for r in rows], total=total, limit=limit, offset=offset)

    async def export_csv(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        actor: str | None,
        action: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> tuple[str, int]:
        await acl.require_admin(self.session, user_id, workspace_id)
        rows, _ = await audit_repo.list_events(
            self.session, workspace_id, actor=actor, action=action, since=since, until=until, limit=EXPORT_LIMIT
        )
        return audit_service.to_csv(list(reversed(rows))), len(rows)  # oldest first, like a ledger

    async def verify(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> a.AuditChainStatus:
        await acl.require_admin(self.session, user_id, workspace_id)
        report = await audit_service.verify_chain(self.session)
        return a.AuditChainStatus(
            ok=report.ok,
            checked=report.checked,
            head_seq=report.head_seq,
            head_hash=report.head_hash,
            first_bad_seq=report.first_bad_seq,
            reason=report.reason,
            starts_at_seq=report.starts_at_seq,
        )


def _to_event(row: AuditEvent) -> a.AuditEvent:
    return a.AuditEvent(
        seq=row.seq,
        created_at=row.created_at,
        actor_id=row.actor_id,
        actor_email=row.actor_email,
        action=row.action,
        target=row.target,
        workspace_id=row.workspace_id,
        metadata=dict(row.event_metadata),
        hash=row.hash,
    )
