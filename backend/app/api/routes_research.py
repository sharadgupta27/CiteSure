from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import ask_limiter, ask_service, current_user
from app.api.ratelimit import RateLimiter
from app.schemas import api as s
from app.services.ask import AskService

router = APIRouter(tags=["public-research"])


@router.get("/public-research", operation_id="getPublicResearchStatus", response_model=s.PublicResearchStatus)
async def get_public_research_status(
    _: s.User = Depends(current_user), svc: AskService = Depends(ask_service)
) -> s.PublicResearchStatus:
    return svc.public_status()


@router.post("/public-research/preview", operation_id="previewPublicQuery", response_model=s.PublicQueryPreview)
async def preview_public_query(
    body: s.PublicQueryPreviewRequest,
    user: s.User = Depends(current_user),
    svc: AskService = Depends(ask_service),
    limiter: RateLimiter = Depends(ask_limiter),
) -> s.PublicQueryPreview:
    limiter.check(f"ask:{user.id}")
    return await svc.preview_public_query(body)
