"""Questions, answers, threads and feedback."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import Forbidden, NotFound, UpstreamError
from app.models import Answer as AnswerRow
from app.observability import StageTimer
from app.providers import Providers
from app.rag.types import PipelineConfig
from app.rag.verification import REFUSAL_MESSAGE
from app.repositories import asks as asks_repo
from app.repositories import documents as documents_repo
from app.schemas import api as s
from app.services import acl
from app.services.pipeline import PipelineOutcome, default_config, estimate_cost, run_pipeline

TOKEN_WORDS = 3
log = logging.getLogger("citesure.ask")


def outcome_to_json(outcome: PipelineOutcome) -> dict[str, Any]:
    """The stored shape of an answer (plan.md section 4). Only verified claims are ever stored."""
    claims = [
        {
            "text": claim.text,
            "citations": [
                {
                    "chunk_id": str(c.chunk.chunk_id),
                    "document_id": str(c.chunk.document_id),
                    "document_title": c.chunk.document_title,
                    "quote": c.quote,
                    "quote_start": c.quote_start,
                    "quote_end": c.quote_end,
                    "heading_path": c.chunk.heading_path,
                    "page_start": c.chunk.page_start,
                    "page_end": c.chunk.page_end,
                }
                for c in claim.citations
            ],
            "verified": True,
            "verification": {"quote_match": claim.quote_match, "entailment": claim.entailment},
        }
        for claim in outcome.claims
    ]
    refusal = None
    if outcome.refusal is not None:
        refusal = {
            "reason": outcome.refusal.reason,
            "message": outcome.refusal.message,
            "closest_sources": [
                {"document_id": str(c.document_id), "document_title": c.document_title, "chunk_id": str(c.chunk_id)}
                for c in outcome.refusal.closest
            ],
        }
    return {"claims": claims, "refusal": refusal, "dropped_claims": outcome.dropped}


def to_answer(row: AnswerRow) -> s.Answer:
    data = row.answer_json
    return s.Answer(
        id=row.id,
        thread_id=row.thread_id,
        question=row.question,
        status=row.status,
        claims=data["claims"],
        refusal=data["refusal"],
        dropped_claims=data["dropped_claims"],
        latency_ms_by_stage=row.latency_ms_by_stage,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        cost_usd=row.cost_usd,
        created_at=row.created_at,
    )


def answer_text(answer: s.Answer) -> str:
    """Plain text of the verified answer, with [n] markers, used for the streamed `token` events."""
    if answer.status == "refused" or not answer.claims:
        return answer.refusal.message if answer.refusal else REFUSAL_MESSAGE
    return " ".join(
        f"{claim.text} {''.join(f'[{i}]' for i in range(1, len(claim.citations) + 1))}" for claim in answer.claims
    )


class AskService:
    def __init__(self, session: AsyncSession, settings: Settings, providers: Providers) -> None:
        self.session = session
        self.settings = settings
        self.providers = providers

    async def stream(self, user_id: uuid.UUID, body: s.AskRequest) -> AsyncIterator[tuple[str, str | s.Answer]]:
        timer = StageTimer()
        with timer.stage("acl"):
            context = await acl.context_for_workspace(self.session, user_id, body.workspace_id)
        config = self._config(context.is_admin, body.config)

        thread = None
        if body.thread_id is not None:
            thread = await asks_repo.get_thread(self.session, body.thread_id, user_id)
            if thread is None or thread.workspace_id != body.workspace_id:
                raise NotFound("Thread not found")
        if thread is None:
            thread = await asks_repo.create_thread(self.session, user_id, body.workspace_id, body.question)
            await self.session.commit()

        outcome: PipelineOutcome | None = None
        try:
            async for kind, payload in run_pipeline(
                self.session,
                self.providers,
                self.settings,
                allowed_collection_ids=context.allowed_collection_ids,
                question=body.question,
                config=config,
                timer=timer,
            ):
                if kind == "stage":
                    assert isinstance(payload, str)
                    yield "stage", payload
                else:
                    assert isinstance(payload, PipelineOutcome)
                    outcome = payload
        except Exception as exc:
            if isinstance(exc, (Forbidden, NotFound)):
                raise
            log.warning("answer pipeline failed: %s", type(exc).__name__)  # type only: messages may echo document text
            raise UpstreamError("The answer service is temporarily unavailable. Please try again.") from exc
        assert outcome is not None

        row = await asks_repo.create_answer(
            self.session,
            thread_id=thread.id,
            user_id=user_id,
            workspace_id=body.workspace_id,
            question=body.question,
            answer_json=outcome_to_json(outcome),
            status=outcome.status,
            retrieved_chunk_ids=[c.chunk_id for c in outcome.retrieved],
            config_snapshot={
                **config.as_dict(),
                "answer_model": self.providers.llm.answer_model,
                "verify_model": self.providers.llm.verify_model,
                "quote_match_min": self.settings.quote_match_min,
                "prompt": "answer_v1",
            },
            latency_ms_by_stage=outcome.timings,
            tokens_in=outcome.usage_answer.tokens_in + outcome.usage_verify.tokens_in,
            tokens_out=outcome.usage_answer.tokens_out + outcome.usage_verify.tokens_out,
            cost_usd=estimate_cost(self.settings, outcome.usage_answer, outcome.usage_verify),
        )
        await self.session.commit()
        answer = to_answer(row)

        # Only verified text is ever streamed, and only after verification finished.
        words = answer_text(answer).split(" ")
        for start in range(0, len(words), TOKEN_WORDS):
            yield "token", " ".join(words[start : start + TOKEN_WORDS]) + " "
        yield "final", answer

    async def ask(self, user_id: uuid.UUID, body: s.AskRequest) -> s.Answer:
        final: s.Answer | None = None
        async for kind, payload in self.stream(user_id, body):
            if kind == "final":
                assert isinstance(payload, s.Answer)
                final = payload
        assert final is not None
        return final

    def _config(self, is_admin: bool, override: s.PipelineConfig | None) -> PipelineConfig:
        if override is None:
            return default_config(self.settings)
        if not is_admin:
            raise Forbidden("Only workspace admins can override the pipeline configuration")
        return PipelineConfig(**override.model_dump())

    # --- reading stored answers: the ACL is re-checked, because access may have been revoked since ---------
    async def _recheck(self, user_id: uuid.UUID, rows: list[AnswerRow]) -> list[s.Answer]:
        """Drop every citation (and closest-source link) the caller can no longer read, in one SQL lookup."""
        answers = [to_answer(r) for r in rows]
        referenced = {c.chunk_id for a in answers for claim in a.claims for c in claim.citations}
        referenced |= {c.chunk_id for a in answers if a.refusal for c in a.refusal.closest_sources}
        visible = await documents_repo.visible_chunk_ids(
            self.session,
            list(referenced),
            allowed_collection_ids=await acl.allowed_collection_ids(self.session, user_id),
        )
        out: list[s.Answer] = []
        for answer in answers:
            claims = []
            for claim in answer.claims:
                citations = [c for c in claim.citations if c.chunk_id in visible]
                if citations:
                    claims.append(claim.model_copy(update={"citations": citations}))
            refusal = answer.refusal
            if refusal is not None:
                kept = [c for c in refusal.closest_sources if c.chunk_id in visible]
                refusal = refusal.model_copy(update={"closest_sources": kept})
            if claims or answer.status == "refused":
                out.append(answer.model_copy(update={"claims": claims, "refusal": refusal}))
            else:  # every citation became unreadable: show a refusal rather than a claim nobody may verify
                refusal = s.Refusal(reason="no_supported_claims", message=REFUSAL_MESSAGE, closest_sources=[])
                out.append(answer.model_copy(update={"claims": [], "status": "refused", "refusal": refusal}))
        return out

    async def _readable_row(self, user_id: uuid.UUID, answer_id: uuid.UUID) -> AnswerRow:
        row = await asks_repo.get_answer(self.session, answer_id)
        if row is None:
            raise NotFound("Answer not found")
        if row.user_id != user_id:
            context = await acl.context_for_workspace(self.session, user_id, row.workspace_id)
            if not context.is_admin:
                raise NotFound("Answer not found")
        return row

    async def get_answer(self, user_id: uuid.UUID, answer_id: uuid.UUID) -> s.Answer:
        row = await self._readable_row(user_id, answer_id)
        return (await self._recheck(user_id, [row]))[0]

    async def list_threads(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> list[s.Thread]:
        await acl.context_for_workspace(self.session, user_id, workspace_id)
        rows = await asks_repo.list_threads(self.session, user_id, workspace_id)
        return [s.Thread.model_validate(r) for r in rows]

    async def get_thread(self, user_id: uuid.UUID, thread_id: uuid.UUID) -> s.ThreadDetail:
        thread = await asks_repo.get_thread(self.session, thread_id, user_id)
        if thread is None:
            raise NotFound("Thread not found")
        answers = await self._recheck(user_id, list(await asks_repo.list_answers(self.session, thread_id)))
        return s.ThreadDetail(
            id=thread.id, workspace_id=thread.workspace_id, title=thread.title, created_at=thread.created_at, answers=answers
        )

    # --- feedback ---------------------------------------------------------------------------
    async def create_feedback(self, user_id: uuid.UUID, answer_id: uuid.UUID, body: s.FeedbackCreate) -> s.Feedback:
        row = await self._readable_row(user_id, answer_id)
        fb = await asks_repo.create_feedback(self.session, row.id, user_id, body.rating, body.comment)
        await self.session.commit()
        return s.Feedback.model_validate(fb)

    async def list_feedback(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> list[s.FeedbackItem]:
        await acl.require_admin(self.session, user_id, workspace_id)
        rows = await asks_repo.list_feedback(self.session, workspace_id)
        return [
            s.FeedbackItem(
                id=f.id,
                answer_id=f.answer_id,
                user_id=f.user_id,
                rating=f.rating,
                comment=f.comment,
                created_at=f.created_at,
                question=a.question,
                answer_status=a.status,
                promoted=promoted,
            )
            for f, a, promoted in rows
        ]
