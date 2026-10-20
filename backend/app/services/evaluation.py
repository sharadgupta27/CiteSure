"""Golden questions, evaluation runs and retrieval diagnostics (admin features)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import Conflict, InvalidInput, NotFound
from app.models import EvalRun as EvalRunRow
from app.models import GoldenQuestion as GoldenRow
from app.providers import Providers
from app.rag.retrieval import retrieve
from app.rag.text import normalise_ws
from app.rag.types import PipelineConfig, ScoredChunk
from app.repositories import asks as asks_repo
from app.repositories import evals as evals_repo
from app.repositories import jobs as jobs_repo
from app.schemas import api as s
from app.services import acl
from app.services.pipeline import default_config

EVAL_JOB = "eval_run"


def to_golden(row: GoldenRow) -> s.GoldenQuestion:
    return s.GoldenQuestion(
        id=row.id,
        workspace_id=row.workspace_id,
        question=row.question,
        expected_answer=row.expected_answer,
        expected_quotes=[s.ExpectedQuote(**q) for q in row.expected_quotes],
        answerable=row.answerable,
        ask_as=row.ask_as,
        source=row.source,
        tags=list(row.tags or []),
        reason=row.reason,
        created_at=row.created_at,
    )


def to_run(row: EvalRunRow) -> s.EvalRun:
    return s.EvalRun(
        id=row.id,
        workspace_id=row.workspace_id,
        name=row.name,
        config=s.PipelineConfig(**row.config),
        status=row.status,
        metrics=s.EvalMetrics(**row.metrics) if row.metrics else None,
        error=row.error,
        created_at=row.created_at,
    )


def _candidates(chunks: list[ScoredChunk]) -> list[s.Candidate]:
    return [
        s.Candidate(
            chunk_id=c.chunk_id,
            document_title=c.document_title,
            rank=i,
            score=round(c.score, 6),
            snippet=normalise_ws(c.text)[:160],
        )
        for i, c in enumerate(chunks, start=1)
    ]


class EvaluationService:
    def __init__(self, session: AsyncSession, settings: Settings, providers: Providers) -> None:
        self.session = session
        self.settings = settings
        self.providers = providers

    # --- golden set ---------------------------------------------------------------------------
    async def list_golden(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> list[s.GoldenQuestion]:
        await acl.require_admin(self.session, user_id, workspace_id)
        return [to_golden(r) for r in await evals_repo.list_golden(self.session, workspace_id)]

    async def create_golden(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID, body: s.GoldenQuestionCreate
    ) -> s.GoldenQuestion:
        await acl.require_admin(self.session, user_id, workspace_id)
        self._validate(body.answerable, body.expected_quotes)
        row = await evals_repo.create_golden(
            self.session,
            workspace_id=workspace_id,
            question=body.question.strip(),
            expected_answer=body.expected_answer,
            expected_quotes=[q.model_dump() for q in body.expected_quotes],
            answerable=body.answerable,
            ask_as=body.ask_as,
            source="manual",
            tags=body.tags,
            reason=body.reason,
        )
        await self.session.commit()
        return to_golden(row)

    async def update_golden(
        self, user_id: uuid.UUID, golden_id: uuid.UUID, body: s.GoldenQuestionUpdate
    ) -> s.GoldenQuestion:
        row = await self._golden_for_admin(user_id, golden_id)
        updates = body.model_dump(exclude_unset=True, exclude={"reason"})
        for key, value in updates.items():
            if key == "expected_quotes" and value is not None:
                value = [q if isinstance(q, dict) else q.model_dump() for q in value]
            if value is not None or key in {"expected_answer", "ask_as"}:
                setattr(row, key, value)
        self._validate(row.answerable, row.expected_quotes)
        row.reason = f"{body.reason} (previous: {row.reason})"[:2000]
        await self.session.commit()
        return to_golden(row)

    async def delete_golden(self, user_id: uuid.UUID, golden_id: uuid.UUID) -> None:
        await self._golden_for_admin(user_id, golden_id)
        await evals_repo.delete_golden(self.session, golden_id)
        await self.session.commit()

    async def promote_feedback(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID, feedback_id: uuid.UUID, body: s.PromoteFeedbackRequest
    ) -> s.GoldenQuestion:
        await acl.require_admin(self.session, user_id, workspace_id)
        feedback = await asks_repo.get_feedback(self.session, feedback_id)
        answer = await asks_repo.get_answer(self.session, feedback.answer_id) if feedback else None
        if feedback is None or answer is None or answer.workspace_id != workspace_id:
            raise NotFound("Feedback not found")
        self._validate(body.answerable, body.expected_quotes)
        try:
            row = await evals_repo.create_golden(
                self.session,
                workspace_id=workspace_id,
                question=answer.question,
                expected_answer=body.expected_answer,
                expected_quotes=[q.model_dump() for q in body.expected_quotes],
                answerable=body.answerable,
                ask_as=body.ask_as,
                source="feedback",
                feedback_id=feedback_id,
                tags=["from-feedback"],
                reason=body.reason,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise Conflict("This feedback was already promoted") from exc
        return to_golden(row)

    async def _golden_for_admin(self, user_id: uuid.UUID, golden_id: uuid.UUID) -> GoldenRow:
        row = await evals_repo.get_golden(self.session, golden_id)
        if row is None:
            raise NotFound("Golden question not found")
        await acl.require_admin(self.session, user_id, row.workspace_id)
        return row

    @staticmethod
    def _validate(answerable: bool, quotes: Sequence[object]) -> None:
        if answerable and not quotes:
            raise InvalidInput("An answerable golden question needs at least one expected quote")

    # --- evaluation runs ----------------------------------------------------------------------
    async def create_run(self, user_id: uuid.UUID, workspace_id: uuid.UUID, body: s.EvalRunCreate) -> s.EvalRun:
        await acl.require_admin(self.session, user_id, workspace_id)
        run = await evals_repo.create_run(self.session, workspace_id, body.name, body.config.model_dump(), user_id)
        await jobs_repo.enqueue(self.session, EVAL_JOB, {"run_id": str(run.id)}, max_attempts=1)
        await self.session.commit()
        return to_run(run)

    async def list_runs(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> list[s.EvalRun]:
        await acl.require_admin(self.session, user_id, workspace_id)
        return [to_run(r) for r in await evals_repo.list_runs(self.session, workspace_id)]

    async def _run_for_admin(self, user_id: uuid.UUID, run_id: uuid.UUID) -> EvalRunRow:
        run = await evals_repo.get_run(self.session, run_id)
        if run is None:
            raise NotFound("Evaluation run not found")
        await acl.require_admin(self.session, user_id, run.workspace_id)
        return run

    async def get_run(self, user_id: uuid.UUID, run_id: uuid.UUID) -> s.EvalRunDetail:
        run = await self._run_for_admin(user_id, run_id)
        items = await evals_repo.list_items(self.session, run_id)
        base = to_run(run)
        return s.EvalRunDetail(
            **base.model_dump(),
            items=[
                s.EvalItem(
                    golden_question_id=i.golden_question_id,
                    question=i.question,
                    answerable=i.answerable,
                    answer_status=i.answer_status,
                    hit_rank=i.hit_rank,
                    scores={k: float(v) for k, v in i.scores.items()},
                )
                for i in items
            ],
        )

    async def compare(self, user_id: uuid.UUID, base_id: uuid.UUID, head_id: uuid.UUID) -> s.EvalCompare:
        base = await self._run_for_admin(user_id, base_id)
        head = await self._run_for_admin(user_id, head_id)
        if base.workspace_id != head.workspace_id:
            raise NotFound("Evaluation run not found")
        if not base.metrics or not head.metrics:
            raise InvalidInput("Both runs must be finished before they can be compared")
        deltas = {
            key: round(float(head.metrics[key]) - float(base.metrics[key]), 4)
            for key in head.metrics
            if key in base.metrics and key != "n_questions"
        }
        return s.EvalCompare(base=to_run(base), head=to_run(head), deltas=deltas)

    # --- diagnostics --------------------------------------------------------------------------
    async def explain(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID, query: str, retrieval_mode: str, rerank: bool
    ) -> s.RetrievalExplain:
        # Any member may explain a query: the trace only contains chunks their own ACL allows, so it adds no access.
        context = await acl.context_for_workspace(self.session, user_id, workspace_id)
        base = default_config(self.settings)
        config = PipelineConfig(
            retrieval_mode=retrieval_mode,  # type: ignore[arg-type]
            rerank=rerank,
            candidate_k=base.candidate_k,
            top_k=base.top_k,
        )
        trace = await retrieve(
            self.session,
            self.providers.embedder,
            self.providers.reranker,
            query,
            context.allowed_collection_ids,
            config,
        )
        return s.RetrievalExplain(
            query=query,
            config=s.PipelineConfig(**config.as_dict()),
            allowed_collections=len(context.allowed_collection_ids),
            vector=_candidates(trace.vector),
            fts=_candidates(trace.fts),
            fused=_candidates(trace.fused),
            reranked=_candidates(trace.reranked),
        )
