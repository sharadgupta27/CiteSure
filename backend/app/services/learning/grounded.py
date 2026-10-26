"""Grounded generation for the learning agents: the same generate -> verify -> refusal-policy stages as /ask
(services/pipeline.py), fed with chunks chosen by the agent instead of by a question.

Nothing generated reaches the user without passing `verify_draft`: a claim needs a quote found in its chunk (fuzzy
>= QUOTE_MATCH_MIN) and an entailment verdict of `supported`. Unsupported claims are dropped and, if none survive, the
result is a refusal. There is deliberately no way to skip verification here (non-negotiable 2)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, UpstreamError
from app.llm.base import GenerationRequest, Usage
from app.models import Answer as AnswerRow
from app.observability import ASK_COST, CLAIMS_DRAFTED, CLAIMS_DROPPED, StageTimer
from app.providers import Providers
from app.rag.generation.prompt import build_sources, load_prompt, render_user_message
from app.rag.types import RetrievalTrace, ScoredChunk
from app.rag.verification import RefusalInfo, refusal_for, verify_draft
from app.rag.verification.policy import closest_sources
from app.repositories import asks as asks_repo
from app.services.ask import outcome_to_json
from app.services.pipeline import PipelineOutcome, choose_llm, ensure_lane_safe, estimate_cost

SUMMARY_PROMPT = "summarize_v1"
COMPARE_PROMPT = "compare_v1"
PLAN_STEP_PROMPT = "plan_step_v1"

Task = Literal["answer", "summary", "compare"]
log = logging.getLogger("citesure.learning")


@dataclass(frozen=True)
class GroundedJob:
    task: Task
    prompt: str  # a versioned file in rag/generation/prompts/
    instruction: str  # shown to the model inside <question>
    focus: str = (
        ""  # the user's own words (topic, aspect, focus); the offline fake model reads it, real models do not need it
    )


@dataclass(frozen=True)
class GroundedRun:
    outcome: PipelineOutcome
    answer_model: str
    verify_model: str
    prompt: str


async def run_grounded(
    providers: Providers, settings: Settings, chunks: Sequence[ScoredChunk], job: GroundedJob
) -> GroundedRun:
    """Generate claims from `chunks` and verify them. `chunks` were read under the caller's ACL; they are company text,
    so `choose_llm` is told so and the answering model is always the internal one (a local model in private mode)."""
    timer = StageTimer()
    llm = choose_llm(providers, internal_text=True, question_cleared=False)
    sources = list(chunks)
    ensure_lane_safe(settings, llm, sources)
    claims = []
    dropped = drafted = 0
    usage_answer = Usage()
    usage_verify = Usage()
    if sources:
        blocks, id_map = build_sources(sources)
        request = GenerationRequest(
            system=load_prompt(job.prompt),
            user=render_user_message(job.instruction, blocks),
            question=job.focus,
            sources=blocks,
            task=job.task,
        )
        with timer.stage("generate"):
            draft, usage_answer = await llm.generate_answer(request)
        drafted = len(draft.claims)
        with timer.stage("verify"):
            verified = await verify_draft(
                draft, id_map, llm, quote_match_min=settings.quote_match_min, min_quote_chars=settings.min_quote_chars
            )
        claims, dropped, usage_verify = verified.claims, verified.dropped, verified.usage

    status: Literal["answered", "refused"] = "answered" if claims else "refused"
    refusal: RefusalInfo | None = None
    if not claims:
        base = refusal_for(sources)
        refusal = RefusalInfo(base.reason, base.message, closest_sources(sources))
    cost = estimate_cost(settings, usage_answer, usage_verify) if llm.hosted else 0.0
    CLAIMS_DRAFTED.inc(drafted)
    CLAIMS_DROPPED.inc(dropped)
    ASK_COST.inc(cost)
    outcome = PipelineOutcome(
        status=status,
        claims=claims,
        refusal=refusal,
        dropped=dropped,
        drafted=drafted,
        retrieved=sources,
        trace=RetrievalTrace(),
        timings=dict(timer.ms),
        usage_answer=usage_answer,
        usage_verify=usage_verify,
        hosted=llm.hosted,
        cost_usd=cost,
    )
    return GroundedRun(outcome, llm.answer_model, llm.verify_model, job.prompt)


async def generate(providers: Providers, settings: Settings, chunks: Sequence[ScoredChunk], job: GroundedJob) -> GroundedRun:
    """`run_grounded`, with model failures reported like /ask reports them: a 502 that never echoes document text."""
    try:
        return await run_grounded(providers, settings, chunks, job)
    except AppError:
        raise
    except Exception as exc:
        log.warning("learning generation failed: %s", type(exc).__name__)  # type only: messages may echo document text
        raise UpstreamError("The answer service is temporarily unavailable. Please try again.") from exc


async def store_run(
    session: AsyncSession,
    settings: Settings,
    run: GroundedRun,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    thread_id: uuid.UUID,
    question: str,
    task: str,
    notices: Sequence[str] = (),
) -> AnswerRow:
    """Persist a run as an ordinary `answers` row, so GET /answers/{id}, feedback, the ACL re-check on read and the
    erase-on-delete scrub all apply to it. Not committed: the caller commits once everything is built."""
    outcome = run.outcome
    data = outcome_to_json(outcome)
    data["notices"] = [*notices]
    return await asks_repo.create_answer(
        session,
        thread_id=thread_id,
        user_id=user_id,
        workspace_id=workspace_id,
        question=question,
        answer_json=data,
        status=outcome.status,
        retrieved_chunk_ids=[c.chunk_id for c in outcome.retrieved],
        config_snapshot={
            "task": task,
            "prompt": run.prompt,
            "answer_model": run.answer_model,
            "verify_model": run.verify_model,
            "quote_match_min": settings.quote_match_min,
            "private_mode": settings.private_mode,
            "hosted_model_used": outcome.hosted,
        },
        latency_ms_by_stage=outcome.timings,
        tokens_in=outcome.usage_answer.tokens_in + outcome.usage_verify.tokens_in,
        tokens_out=outcome.usage_answer.tokens_out + outcome.usage_verify.tokens_out,
        cost_usd=outcome.cost_usd,
    )
