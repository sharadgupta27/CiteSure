"""Operations dashboard (workspace admins only; the service enforces it)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import current_user
from app.api.deps_admin import dashboard_service
from app.schemas import admin as a
from app.schemas import api as s
from app.services.dashboard import DashboardService

router = APIRouter(tags=["dashboard"])


@router.get("/workspaces/{workspace_id}/dashboard", operation_id="getDashboard", response_model=a.Dashboard)
async def get_dashboard(
    workspace_id: uuid.UUID,
    days: int = Query(30, ge=1, le=365),
    user: s.User = Depends(current_user),
    svc: DashboardService = Depends(dashboard_service),
) -> a.Dashboard:
    return await svc.get(user.id, workspace_id, days)
