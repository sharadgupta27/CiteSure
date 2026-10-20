"""Threads, answers and feedback."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import bindparam, select
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Answer, Feedback, GoldenQuestion, Thread


async def create_thread(session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID, title: str) -> Thread:
    thread = Thread(user_id=user_id, workspace_id=workspace_id, title=title[:200])
    session.add(thread)
    await session.flush()
    return thread


async def get_thread(session: AsyncSession, thread_id: uuid.UUID, user_id: uuid.UUID) -> Thread | None:
    stmt = select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_threads(session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID) -> Sequence[Thread]:
    stmt = (
        select(Thread)
        .where(Thread.user_id == user_id, Thread.workspace_id == workspace_id)
        .order_by(Thread.created_at.desc())
    )
    return (await session.execute(stmt)).scalars().all()


async def create_answer(
    session: AsyncSession,
    *,
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    question: str,
    answer_json: dict[str, Any],
    status: str,
    retrieved_chunk_ids: list[uuid.UUID],
    config_snapshot: dict[str, Any],
    latency_ms_by_stage: dict[str, float],
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
) -> Answer:
    answer = Answer(
        thread_id=thread_id,
        user_id=user_id,
        workspace_id=workspace_id,
        question=question,
        answer_json=answer_json,
        status=status,
        retrieved_chunk_ids=retrieved_chunk_ids,
        config_snapshot=config_snapshot,
        latency_ms_by_stage=latency_ms_by_stage,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )
    session.add(answer)
    await session.flush()
    return answer


async def get_answer(session: AsyncSession, answer_id: uuid.UUID) -> Answer | None:
    return await session.get(Answer, answer_id)


async def list_answers(session: AsyncSession, thread_id: uuid.UUID) -> Sequence[Answer]:
    stmt = select(Answer).where(Answer.thread_id == thread_id).order_by(Answer.created_at)
    return (await session.execute(stmt)).scalars().all()


async def create_feedback(
    session: AsyncSession, answer_id: uuid.UUID, user_id: uuid.UUID, rating: int, comment: str | None
) -> Feedback:
    fb = Feedback(answer_id=answer_id, user_id=user_id, rating=rating, comment=comment)
    session.add(fb)
    await session.flush()
    return fb


async def get_feedback(session: AsyncSession, feedback_id: uuid.UUID) -> Feedback | None:
    return await session.get(Feedback, feedback_id)


async def list_feedback(session: AsyncSession, workspace_id: uuid.UUID) -> Sequence[tuple[Feedback, Answer, bool]]:
    promoted = select(GoldenQuestion.id).where(GoldenQuestion.feedback_id == Feedback.id).exists()
    stmt = (
        select(Feedback, Answer, promoted)
        .join(Answer, Answer.id == Feedback.answer_id)
        .where(Answer.workspace_id == workspace_id)
        .order_by(Feedback.created_at.desc())
    )
    return [(f, a, bool(p)) for f, a, p in (await session.execute(stmt)).all()]


async def scrub_deleted_chunks(session: AsyncSession, chunk_ids: Sequence[uuid.UUID]) -> int:
    """Erase quoted document text from stored answers when its source chunks are deleted (right to erasure).

    Citations to the deleted chunks are removed; a claim left without any citation is removed; an answer left without
    claims becomes a refusal. The question text and the user's feedback are untouched. Returns the answers changed."""
    if not chunk_ids:
        return 0
    gone = {str(c) for c in chunk_ids}
    ids = bindparam("ids", list(chunk_ids), type_=PG_ARRAY(PGUUID(as_uuid=True)))
    rows = (
        (await session.execute(select(Answer).where(Answer.retrieved_chunk_ids.op("&&")(ids)))).scalars().all()
    )  # array overlap
    for row in rows:
        data = row.answer_json
        claims = []
        for claim in data.get("claims", []):
            citations = [c for c in claim["citations"] if c["chunk_id"] not in gone]
            if citations:
                claims.append({**claim, "citations": citations})
        refusal = data.get("refusal")
        if refusal:
            refusal = {**refusal, "closest_sources": [c for c in refusal["closest_sources"] if c["chunk_id"] not in gone]}
        if not claims and row.status == "answered":
            row.status = "refused"
            refusal = {
                "reason": "no_supported_claims",
                "message": "The source of this answer was deleted.",
                "closest_sources": [],
            }
        row.answer_json = {**data, "claims": claims, "refusal": refusal}  # a new object, so the JSONB change is detected
        row.retrieved_chunk_ids = [c for c in row.retrieved_chunk_ids if str(c) not in gone]
    await session.flush()
    return len(rows)
