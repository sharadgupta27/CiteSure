from __future__ import annotations

import contextlib

from fastapi import APIRouter, Depends, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.observability import QUEUE_DEPTH
from app.repositories import jobs as jobs_repo
from app.schemas import api as s

router = APIRouter(tags=["ops"])


@router.get("/healthz", operation_id="healthz", response_model=s.Health)
async def healthz(session: AsyncSession = Depends(get_session)) -> s.Health:
    try:
        await session.execute(text("SELECT 1"))
        return s.Health(status="ok", database=True)
    except Exception:
        return s.Health(status="degraded", database=False)


@router.get("/metrics", operation_id="metrics", response_class=Response)
async def metrics(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    with contextlib.suppress(Exception):  # metrics must keep working when the database is down
        QUEUE_DEPTH.set(await jobs_repo.queue_depth(session))
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
