"""Learning plans and their steps. Plans are private to their owner; steps are listed only while the caller may read
the step's document (decided in SQL), so a plan never reveals the title of a document that became unreadable."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Answer, Document, Thread
from app.models.learning import LearningPlan, PlanStep


async def create_plan(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    study_set_id: uuid.UUID | None,
    thread_id: uuid.UUID | None,
    title: str,
    topic: str | None,
    hours_per_week: float,
) -> LearningPlan:
    plan = LearningPlan(
        user_id=user_id,
        workspace_id=workspace_id,
        study_set_id=study_set_id,
        thread_id=thread_id,
        title=title,
        topic=topic,
        hours_per_week=hours_per_week,
    )
    session.add(plan)
    await session.flush()
    return plan


async def add_step(
    session: AsyncSession,
    *,
    plan_id: uuid.UUID,
    position: int,
    week: int,
    document_id: uuid.UUID,
    label: str,
    page_start: int | None,
    page_end: int | None,
    ord_start: int,
    ord_end: int,
    est_minutes: int,
    answer_id: uuid.UUID | None,
) -> PlanStep:
    step = PlanStep(
        plan_id=plan_id,
        position=position,
        week=week,
        document_id=document_id,
        label=label,
        page_start=page_start,
        page_end=page_end,
        ord_start=ord_start,
        ord_end=ord_end,
        est_minutes=est_minutes,
        answer_id=answer_id,
    )
    session.add(step)
    await session.flush()
    return step


async def get_plan(session: AsyncSession, plan_id: uuid.UUID, user_id: uuid.UUID) -> LearningPlan | None:
    stmt = select(LearningPlan).where(LearningPlan.id == plan_id, LearningPlan.user_id == user_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_plans(session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID) -> Sequence[LearningPlan]:
    stmt = (
        select(LearningPlan)
        .where(LearningPlan.user_id == user_id, LearningPlan.workspace_id == workspace_id)
        .order_by(LearningPlan.created_at.desc())
    )
    return (await session.execute(stmt)).scalars().all()


async def delete_plan(session: AsyncSession, plan_id: uuid.UUID) -> None:
    await session.execute(delete(LearningPlan).where(LearningPlan.id == plan_id))


async def delete_thread(session: AsyncSession, thread_id: uuid.UUID) -> None:
    """The plan's own thread; its answers (the step objectives) go with it."""
    await session.execute(delete(Thread).where(Thread.id == thread_id))


async def visible_steps(
    session: AsyncSession, plan_ids: Sequence[uuid.UUID], *, allowed_collection_ids: Sequence[uuid.UUID]
) -> list[tuple[PlanStep, Document, Answer | None]]:
    """Steps of these plans whose document the caller may read, in plan order, with the answer holding the objective."""
    if not plan_ids:
        return []
    stmt = (
        select(PlanStep, Document, Answer)
        .join(Document, Document.id == PlanStep.document_id)
        .outerjoin(Answer, Answer.id == PlanStep.answer_id)
        .where(PlanStep.plan_id.in_(plan_ids), Document.collection_id.in_(allowed_collection_ids))
        .order_by(PlanStep.plan_id, PlanStep.position)
    )
    return [(s, d, a) for s, d, a in (await session.execute(stmt)).all()]


async def get_step(session: AsyncSession, plan_id: uuid.UUID, step_id: uuid.UUID) -> PlanStep | None:
    stmt = select(PlanStep).where(PlanStep.id == step_id, PlanStep.plan_id == plan_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_done(session: AsyncSession, step: PlanStep, done_at: datetime | None) -> None:
    step.done_at = done_at
    await session.flush()
