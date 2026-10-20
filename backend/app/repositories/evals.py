"""Golden questions and evaluation runs."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EvalItem, EvalRun, GoldenQuestion


async def create_golden(session: AsyncSession, **values: Any) -> GoldenQuestion:
    golden = GoldenQuestion(**values)
    session.add(golden)
    await session.flush()
    return golden


async def get_golden(session: AsyncSession, golden_id: uuid.UUID) -> GoldenQuestion | None:
    return await session.get(GoldenQuestion, golden_id)


async def list_golden(session: AsyncSession, workspace_id: uuid.UUID) -> Sequence[GoldenQuestion]:
    stmt = (
        select(GoldenQuestion)
        .where(GoldenQuestion.workspace_id == workspace_id)
        .order_by(GoldenQuestion.created_at, GoldenQuestion.id)
    )
    return (await session.execute(stmt)).scalars().all()


async def delete_golden(session: AsyncSession, golden_id: uuid.UUID) -> None:
    await session.execute(delete(GoldenQuestion).where(GoldenQuestion.id == golden_id))


async def create_run(
    session: AsyncSession, workspace_id: uuid.UUID, name: str, config: dict[str, Any], created_by: uuid.UUID | None
) -> EvalRun:
    run = EvalRun(workspace_id=workspace_id, name=name, config=config, created_by=created_by)
    session.add(run)
    await session.flush()
    return run


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> EvalRun | None:
    return await session.get(EvalRun, run_id)


async def list_runs(session: AsyncSession, workspace_id: uuid.UUID) -> Sequence[EvalRun]:
    stmt = select(EvalRun).where(EvalRun.workspace_id == workspace_id).order_by(EvalRun.created_at.desc())
    return (await session.execute(stmt)).scalars().all()


async def list_items(session: AsyncSession, run_id: uuid.UUID) -> Sequence[EvalItem]:
    stmt = select(EvalItem).where(EvalItem.eval_run_id == run_id).order_by(EvalItem.question)
    return (await session.execute(stmt)).scalars().all()


async def add_item(session: AsyncSession, **values: Any) -> None:
    session.add(EvalItem(**values))
    await session.flush()


async def set_run_state(
    session: AsyncSession, run_id: uuid.UUID, status: str, *, metrics: dict[str, Any] | None = None, error: str | None = None
) -> None:
    run = await session.get(EvalRun, run_id)
    if run is not None:
        run.status = status
        run.error = error
        if metrics is not None:
            run.metrics = metrics


async def delete_items(session: AsyncSession, run_id: uuid.UUID) -> None:
    await session.execute(delete(EvalItem).where(EvalItem.eval_run_id == run_id))
