"""The RAG pipeline as one composable unit: retrieve -> (research) -> generate -> verify -> apply the refusal policy.

The ACL has already been resolved by the caller; this module receives the allowed collection ids and passes them to
retrieval, which filters in SQL. Each stage is a separate, swappable function (see app/rag/).

Two lanes feed one answer (docs/public-research.md):
- the INTERNAL lane retrieves the company's own documents (scope `internal` or `both`);
- the PUBLIC lane searches published papers and web pages through the egress guard (scope `public` or `both`).

`choose_llm` is the single place that decides which model reads which text. Company text only ever goes to
`providers.llm` (a local model in private mode); a hosted model reads public passages and a guard-cleared question."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.egress.corpus import SqlInternalCorpus
from app.errors import AppError
from app.llm.base import GenerationRequest, LLMProvider, Usage
from app.observability import ASK_COST, ASK_TOTAL, CLAIMS_DRAFTED, CLAIMS_DROPPED, PUBLIC_ASKS, StageTimer
from app.providers import Providers
from app.rag.generation.prompt import (
    ANSWER_PROMPT,
    ANSWER_PROMPT_MIXED,
    build_sources,
    load_prompt,
    render_user_message,
)
from app.rag.retrieval import retrieve
from app.rag.retrieval.fulltext import FullTextRetriever
from app.rag.types import PipelineConfig, RetrievalTrace, ScoredChunk
from app.rag.verification import RefusalInfo, VerifiedClaim, refusal_for, verify_draft
from app.rag.verification.policy import closest_sources
from app.research import EgressRecord

Scope = Literal["internal", "public", "both"]


class PrivacyViolation(AppError):
    """Company text was about to be sent to a hosted model in private mode. Never raised by correct routing; it exists
    so a future change that breaks the rule fails loudly in tests instead of silently leaking."""

    status_code = 500
    code = "privacy_violation"


@dataclass
class PipelineOutcome:
    status: Literal["answered", "refused"]
    claims: list[VerifiedClaim]
    refusal: RefusalInfo | None
    dropped: int
    drafted: int
    retrieved: list[ScoredChunk]  # internal chunks only: these are database rows the caller may read
    trace: RetrievalTrace
    timings: dict[str, float]
    usage_answer: Usage = field(default_factory=Usage)
    usage_verify: Usage = field(default_factory=Usage)
    scope: Scope = "internal"
    public_retrieved: list[ScoredChunk] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    egress: list[EgressRecord] = field(default_factory=list)
    hosted: bool = False  # the answering model ran on someone else's servers (so the usage is billable)
    cost_usd: float = 0.0


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


def choose_llm(providers: Providers, *, internal_text: bool, question_cleared: bool) -> LLMProvider:
    """Which model answers and verifies this request.

    - Any company text in the prompt: the internal model, always.
    - Only public passages: the public model, but only when the egress guard cleared the whole question, because the
      question is part of the prompt. Otherwise the internal model reads the public passages (public text may go
      anywhere; company text and uncleared questions may not).
    """
    if internal_text:
        return providers.llm
    if providers.public_llm is not None and question_cleared:
        return providers.public_llm
    return providers.llm


def ensure_lane_safe(settings: Settings, llm: LLMProvider, sources: Sequence[ScoredChunk]) -> None:
    if settings.private_mode and llm.hosted and any(s.source_type == "internal" for s in sources):
        raise PrivacyViolation("Internal text may not be sent to a hosted model in private mode")


async def run_pipeline(
    session: AsyncSession,
    providers: Providers,
    settings: Settings,
    *,
    allowed_collection_ids: Sequence[uuid.UUID],
    question: str,
    config: PipelineConfig,
    timer: StageTimer | None = None,
    scope: Scope = "internal",
    public_query: str | None = None,
) -> AsyncIterator[tuple[str, str | PipelineOutcome]]:
    """Yields ("stage", name) events, then one ("result", PipelineOutcome)."""
    timer = timer or StageTimer()
    use_internal = scope in ("internal", "both")
    use_public = scope in ("public", "both")

    yield "stage", "retrieving"
    trace = RetrievalTrace()
    if use_internal:
        trace = await retrieve(
            session, providers.embedder, providers.reranker, question, allowed_collection_ids, config, timer
        )
    internal_chunks = trace.final

    notices: list[str] = []
    egress: list[EgressRecord] = []
    public_chunks: list[ScoredChunk] = []
    question_cleared = False
    if use_public:
        yield "stage", "researching"
        if providers.research is None:
            notices.append("Public research is not enabled on this server.")
        else:
            # Open-access papers users added are searched locally and cited like any public passage (phase 3).
            cache = FullTextRetriever(session, providers.embedder, settings.candidate_k) if settings.fulltext_on else None
            research = providers.research.for_request(SqlInternalCorpus(session), cache)
            with timer.stage("research"):
                found = await research.search(question, explicit_query=public_query, reranker=providers.reranker)
            public_chunks, notices, egress, question_cleared = (
                found.chunks,
                found.notices,
                found.records,
                found.question_cleared,
            )
            PUBLIC_ASKS.labels(scope=scope, outcome="results" if public_chunks else "none").inc()

    sources_all = [*internal_chunks, *public_chunks]
    llm = choose_llm(providers, internal_text=bool(internal_chunks), question_cleared=question_cleared)
    claims: list[VerifiedClaim] = []
    dropped = drafted = 0
    usage_answer = Usage()
    usage_verify = Usage()
    if sources_all:
        ensure_lane_safe(settings, llm, sources_all)
        yield "stage", "generating"
        blocks, id_map = build_sources(sources_all)
        request = GenerationRequest(
            system=load_prompt(ANSWER_PROMPT_MIXED if public_chunks else ANSWER_PROMPT),
            user=render_user_message(question, blocks),
            question=question,
            sources=blocks,
        )
        with timer.stage("generate"):
            draft, usage_answer = await llm.generate_answer(request)
        drafted = len(draft.claims)

        yield "stage", "verifying"
        with timer.stage("verify"):
            verified = await verify_draft(
                draft,
                id_map,
                llm,
                quote_match_min=settings.quote_match_min,
                min_quote_chars=settings.min_quote_chars,
            )
        claims, dropped, usage_verify = verified.claims, verified.dropped, verified.usage
        # Claims the model drafted but the verifier rejected are counted as dropped; so are any it never cited.

    status: Literal["answered", "refused"] = "answered" if claims else "refused"
    refusal: RefusalInfo | None = None
    if not claims:
        base = refusal_for(sources_all)
        refusal = RefusalInfo(base.reason, base.message, closest_sources(internal_chunks))  # only rows the caller may read
    cost = estimate_cost(settings, usage_answer, usage_verify) if llm.hosted else 0.0
    ASK_TOTAL.labels(status=status).inc()
    CLAIMS_DRAFTED.inc(drafted)
    CLAIMS_DROPPED.inc(dropped)
    ASK_COST.inc(cost)
    yield (
        "result",
        PipelineOutcome(
            status=status,
            claims=claims,
            refusal=refusal,
            dropped=dropped,
            drafted=drafted,
            retrieved=internal_chunks,
            trace=trace,
            timings=dict(timer.ms),
            usage_answer=usage_answer,
            usage_verify=usage_verify,
            scope=scope,
            public_retrieved=public_chunks,
            notices=notices,
            egress=egress,
            hosted=llm.hosted,
            cost_usd=cost,
        ),
    )
