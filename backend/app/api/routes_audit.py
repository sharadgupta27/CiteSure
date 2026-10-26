"""Audit log reads (workspace admins only; the service enforces it). Entries are written by `services/audit.py`."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import current_user
from app.api.deps_admin import audit_admin_service, audit_log
from app.schemas import admin as a
from app.schemas import api as s
from app.services import audit
from app.services.audit_admin import AuditAdminService

router = APIRouter(tags=["audit"])


@router.get("/workspaces/{workspace_id}/audit-events", operation_id="listAuditEvents", response_model=a.AuditEventPage)
async def list_audit_events(
    workspace_id: uuid.UUID,
    actor: str | None = Query(None, max_length=320, description="User id, or part of an e-mail address"),
    action: str | None = Query(None, max_length=60),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: s.User = Depends(current_user),
    svc: AuditAdminService = Depends(audit_admin_service),
) -> a.AuditEventPage:
    return await svc.list_events(
        user.id, workspace_id, actor=actor, action=action, since=since, until=until, limit=limit, offset=offset
    )


@router.get("/workspaces/{workspace_id}/audit-events/export", operation_id="exportAuditEvents", response_class=Response)
async def export_audit_events(
    workspace_id: uuid.UUID,
    actor: str | None = Query(None, max_length=320),
    action: str | None = Query(None, max_length=60),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    user: s.User = Depends(current_user),
    svc: AuditAdminService = Depends(audit_admin_service),
    log: audit.AuditLog = Depends(audit_log),
) -> Response:
    body, count = await svc.export_csv(user.id, workspace_id, actor=actor, action=action, since=since, until=until)
    await log.record(user, audit.AUDIT_EXPORT, workspace_id=workspace_id, metadata={"rows": count, "action_filter": action})
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"', "X-Content-Type-Options": "nosniff"},
    )


@router.get(
    "/workspaces/{workspace_id}/audit-events/verify", operation_id="verifyAuditChain", response_model=a.AuditChainStatus
)
async def verify_audit_chain(
    workspace_id: uuid.UUID, user: s.User = Depends(current_user), svc: AuditAdminService = Depends(audit_admin_service)
) -> a.AuditChainStatus:
    return await svc.verify(user.id, workspace_id)
