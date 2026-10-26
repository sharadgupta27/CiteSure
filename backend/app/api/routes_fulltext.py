"""Open-access full text of published papers, added on demand (docs/open-access-fulltext.md)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import ask_limiter, current_user, fulltext_service
from app.api.deps_admin import audit_log
from app.api.ratelimit import RateLimiter
from app.schemas import api as s
from app.schemas import fulltext as ft
from app.services.audit import AuditLog
from app.services.fulltext import FullTextService

router = APIRouter(tags=["public-research"])


@router.post(
    "/research/fulltext",
    operation_id="requestFullText",
    response_model=ft.FullTextStatus,
)
async def request_full_text(
    body: ft.FullTextFetchRequest,
    user: s.User = Depends(current_user),
    svc: FullTextService = Depends(fulltext_service),
    limiter: RateLimiter = Depends(ask_limiter),
    audit: AuditLog = Depends(audit_log),
) -> ft.FullTextStatus:
    limiter.check(f"fulltext:{user.id}")
    result = await svc.request(user.id, body)
    # The paper address is public, but only the outcome is recorded: ids and counts, never the question or the text.
    await audit.record(
        user, "fulltext.request", str(result.id), body.workspace_id, {"status": result.status, "cached": result.cached}
    )
    return result


@router.get(
    "/research/fulltext/{request_id}",
    operation_id="getFullTextStatus",
    response_model=ft.FullTextStatus,
)
async def get_full_text_status(
    request_id: uuid.UUID,
    user: s.User = Depends(current_user),
    svc: FullTextService = Depends(fulltext_service),
) -> ft.FullTextStatus:
    return await svc.status(user.id, request_id)
