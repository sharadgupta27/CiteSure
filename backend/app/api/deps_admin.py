"""Dependencies for the phase 5 routes (kept apart from deps.py, which every phase edits)."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.services.audit import AuditLog
from app.services.audit_admin import AuditAdminService
from app.services.dashboard import DashboardService


def audit_log(session: AsyncSession = Depends(get_session)) -> AuditLog:
    """Routes receive this to append audit entries: `await audit.record(user, "document.delete", target=..., ...)`."""
    return AuditLog(session)


def audit_admin_service(session: AsyncSession = Depends(get_session)) -> AuditAdminService:
    return AuditAdminService(session)


def dashboard_service(session: AsyncSession = Depends(get_session)) -> DashboardService:
    return DashboardService(session)
