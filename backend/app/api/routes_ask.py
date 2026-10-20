from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import ask_limiter, ask_service, current_user, get_providers, get_settings
from app.api.ratelimit import RateLimiter
from app.config import Settings
from app.errors import AppError
from app.providers import Providers
from app.schemas import api as s
from app.services.ask import AskService

router = APIRouter()


@router.post("/ask", tags=["ask"], operation_id="ask", response_model=s.Answer)
async def ask(
    body: s.AskRequest,
    user: s.User = Depends(current_user),
    svc: AskService = Depends(ask_service),
    limiter: RateLimiter = Depends(ask_limiter),
) -> s.Answer:
    limiter.check(f"ask:{user.id}")
    return await svc.ask(user.id, body)


def _sse(event: str, data: Any) -> bytes:
    """One Server-Sent Event. Every payload is JSON so text with newlines or quotes cannot break the framing."""
    encoded = data.model_dump_json() if isinstance(data, BaseModel) else json.dumps(data)
    return f"event: {event}\ndata: {encoded}\n\n".encode()


@router.post("/ask/stream", tags=["ask"], operation_id="askStream", response_class=StreamingResponse)
async def ask_stream(
    body: s.AskRequest,
    request: Request,
    user: s.User = Depends(current_user),
    settings: Settings = Depends(get_settings),
    providers: Providers = Depends(get_providers),
    limiter: RateLimiter = Depends(ask_limiter),
) -> StreamingResponse:
    limiter.check(f"ask:{user.id}")
    # The stream outlives the request-scoped dependencies, so it owns its own database session.
    session = request.app.state.sessionmaker()
    events = AskService(session, settings, providers).stream(user.id, body)
    try:
        first = await events.__anext__()  # errors before the first event (404, 403, 422...) become real HTTP errors
    except BaseException:
        await session.close()
        raise

    async def body_iter() -> AsyncIterator[bytes]:
        try:
            yield _sse(*first)
            async for kind, payload in events:
                yield _sse(kind, payload)
        except AppError as exc:
            yield _sse("error", {"code": exc.code, "detail": exc.detail})
        finally:
            await session.close()

    return StreamingResponse(
        body_iter(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/threads", tags=["ask"], operation_id="listThreads", response_model=list[s.Thread])
async def list_threads(
    workspace_id: uuid.UUID = Query(...), user: s.User = Depends(current_user), svc: AskService = Depends(ask_service)
) -> list[s.Thread]:
    return await svc.list_threads(user.id, workspace_id)


@router.get("/threads/{thread_id}", tags=["ask"], operation_id="getThread", response_model=s.ThreadDetail)
async def get_thread(
    thread_id: uuid.UUID, user: s.User = Depends(current_user), svc: AskService = Depends(ask_service)
) -> s.ThreadDetail:
    return await svc.get_thread(user.id, thread_id)


@router.get("/answers/{answer_id}", tags=["ask"], operation_id="getAnswer", response_model=s.Answer)
async def get_answer(
    answer_id: uuid.UUID, user: s.User = Depends(current_user), svc: AskService = Depends(ask_service)
) -> s.Answer:
    return await svc.get_answer(user.id, answer_id)


@router.post(
    "/answers/{answer_id}/feedback",
    tags=["feedback"],
    operation_id="createFeedback",
    status_code=201,
    response_model=s.Feedback,
)
async def create_feedback(
    answer_id: uuid.UUID,
    body: s.FeedbackCreate,
    user: s.User = Depends(current_user),
    svc: AskService = Depends(ask_service),
) -> s.Feedback:
    return await svc.create_feedback(user.id, answer_id, body)


@router.get(
    "/workspaces/{workspace_id}/feedback",
    tags=["feedback"],
    operation_id="listFeedback",
    response_model=list[s.FeedbackItem],
)
async def list_feedback(
    workspace_id: uuid.UUID, user: s.User = Depends(current_user), svc: AskService = Depends(ask_service)
) -> list[s.FeedbackItem]:
    return await svc.list_feedback(user.id, workspace_id)
