"""Phase 2: watched-folder inbox status for workspace admins. The scanning itself runs in the worker."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_session, get_settings
from app.api.deps_admin import audit_log
from app.config import Settings
from app.schemas import api as s
from app.schemas import viewer as v
from app.services.audit import AuditLog
from app.services.inbox import InboxService

router = APIRouter(tags=["inbox"])


def inbox_service(session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> InboxService:
    return InboxService(session, settings)


@router.get("/workspaces/{workspace_id}/inbox", operation_id="getInboxStatus", response_model=v.InboxStatus)
async def get_inbox_status(
    workspace_id: uuid.UUID, user: s.User = Depends(current_user), svc: InboxService = Depends(inbox_service)
) -> v.InboxStatus:
    return await svc.status(user.id, workspace_id)


@router.get("/workspaces/{workspace_id}/inbox/items", operation_id="listInboxItems", response_model=list[v.InboxItem])
async def list_inbox_items(
    workspace_id: uuid.UUID,
    status: v.InboxItemStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    user: s.User = Depends(current_user),
    svc: InboxService = Depends(inbox_service),
) -> list[v.InboxItem]:
    return await svc.items(user.id, workspace_id, status=status, limit=limit)


@router.post(
    "/workspaces/{workspace_id}/inbox/scan", operation_id="requestInboxScan", status_code=202, response_model=v.InboxStatus
)
async def request_inbox_scan(
    workspace_id: uuid.UUID,
    user: s.User = Depends(current_user),
    svc: InboxService = Depends(inbox_service),
    audit: AuditLog = Depends(audit_log),
) -> v.InboxStatus:
    status = await svc.request_scan(user.id, workspace_id)
    await audit.record(user, "inbox.scan_requested", None, workspace_id)
    return status
