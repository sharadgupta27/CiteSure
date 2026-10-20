"""The RAG pipeline as one composable unit: retrieve -> generate -> verify -> apply the refusal policy.

The ACL has already been resolved by the caller; this module receives the allowed collection ids and passes them to
retrieval, which filters in SQL. Each stage is a separate, swappable function (see app/rag/)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.base import GenerationRequest, Usage
from app.observability import ASK_COST, ASK_TOTAL, CLAIMS_DRAFTED, CLAIMS_DROPPED, StageTimer
from app.providers import Providers
from app.rag.generation.prompt import ANSWER_PROMPT, build_sources, load_prompt, render_user_message
from app.rag.retrieval import retrieve
from app.rag.types import PipelineConfig, RetrievalTrace, ScoredChunk
from app.rag.verification import RefusalInfo, VerifiedClaim, refusal_for, verify_draft


@dataclass
class PipelineOutcome:
    status: Literal["answered", "refused"]
    claims: list[VerifiedClaim]
    refusal: RefusalInfo | None
    dropped: int
    drafted: int
    retrieved: list[ScoredChunk]
    trace: RetrievalTrace
    timings: dict[str, float]
    usage_answer: Usage = field(default_factory=Usage)
    usage_verify: Usage = field(default_factory=Usage)


def estimate_cost(settings: Settings, answer: Usage, verify: Usage) -> float:
    return (
        answer.tokens_in * settings.price_in_answer
        + answer.tokens_out * settings.price_out_answer
        + verify.tokens_in * settings.price_in_verify
        + verify.tokens_out * settings.price_out_verify
    ) / 1_000_000


def default_config(settings: Settings) -> PipelineConfig:
    return PipelineConfig(
        retrieval_mode="hybrid",
        rerank=settings.rerank_enabled,
        candidate_k=settings.candidate_k,
        top_k=settings.top_k,
    )


async def run_pipeline(
    session: AsyncSession,
    providers: Providers,
    settings: Settings,
    *,
    allowed_collection_ids: Sequence[uuid.UUID],
    question: str,
    config: PipelineConfig,
    timer: StageTimer | None = None,
) -> AsyncIterator[tuple[str, str | PipelineOutcome]]:
    """Yields ("stage", name) events, then one ("result", PipelineOutcome)."""
    timer = timer or StageTimer()

    yield "stage", "retrieving"
    trace = await retrieve(session, providers.embedder, providers.reranker, question, allowed_collection_ids, config, timer)
    retrieved = trace.final

    claims: list[VerifiedClaim] = []
    dropped = drafted = 0
    usage_answer = Usage()
    usage_verify = Usage()
    if retrieved:
        yield "stage", "generating"
        blocks, id_map = build_sources(retrieved)
        request = GenerationRequest(
            system=load_prompt(ANSWER_PROMPT),
            user=render_user_message(question, blocks),
            question=question,
            sources=blocks,
        )
        with timer.stage("generate"):
            draft, usage_answer = await providers.llm.generate_answer(request)
        drafted = len(draft.claims)

        yield "stage", "verifying"
        with timer.stage("verify"):
            verified = await verify_draft(
                draft,
                id_map,
                providers.llm,
                quote_match_min=settings.quote_match_min,
                min_quote_chars=settings.min_quote_chars,
            )
        claims, dropped, usage_verify = verified.claims, verified.dropped, verified.usage
        # Claims the model drafted but the verifier rejected are counted as dropped; so are any it never cited.

    status: Literal["answered", "refused"] = "answered" if claims else "refused"
    ASK_TOTAL.labels(status=status).inc()
    CLAIMS_DRAFTED.inc(drafted)
    CLAIMS_DROPPED.inc(dropped)
    ASK_COST.inc(estimate_cost(settings, usage_answer, usage_verify))
    yield (
        "result",
        PipelineOutcome(
            status=status,
            claims=claims,
            refusal=None if claims else refusal_for(retrieved),
            dropped=dropped,
            drafted=drafted,
            retrieved=retrieved,
            trace=trace,
            timings=dict(timer.ms),
            usage_answer=usage_answer,
            usage_verify=usage_verify,
        ),
    )
