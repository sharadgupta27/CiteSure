"""Runs both verification stages over a drafted answer and returns only what survived."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from app.llm.base import LLMProvider, Usage
from app.rag.generation.schema import AnswerDraft, DraftClaim
from app.rag.types import ScoredChunk
from app.rag.verification.entailment import check_entailment, evidence_window
from app.rag.verification.quote_match import match_quote


@dataclass(frozen=True)
class VerifiedCitation:
    chunk: ScoredChunk
    quote: str
    quote_start: int
    quote_end: int
    quote_match: float


@dataclass(frozen=True)
class VerifiedClaim:
    text: str
    citations: list[VerifiedCitation]
    quote_match: float
    entailment: Literal["supported", "partial", "unsupported"]


@dataclass
class VerificationResult:
    claims: list[VerifiedClaim] = field(default_factory=list)
    dropped: int = 0
    usage: Usage = field(default_factory=Usage)


async def _verify_claim(
    claim: DraftClaim,
    id_map: dict[str, ScoredChunk],
    llm: LLMProvider,
    *,
    quote_match_min: float,
    min_quote_chars: int,
) -> tuple[VerifiedClaim | None, Usage]:
    passed: list[VerifiedCitation] = []
    for citation in claim.citations:
        chunk = id_map.get(citation.source_id)
        if chunk is None:  # the model cited a source that was never given to it
            continue
        match = match_quote(citation.quote, chunk.text, min_chars=min_quote_chars)
        if match.score >= quote_match_min:
            passed.append(VerifiedCitation(chunk, citation.quote, match.start, match.end, match.score))
    if not passed or not claim.text.strip():
        return None, Usage()

    evidence = "\n---\n".join(evidence_window(c.chunk, c.quote_start, c.quote_end) for c in passed)
    verdict, usage = await check_entailment(llm, claim.text, evidence)
    if verdict.verdict != "supported":
        return None, usage
    best = max(c.quote_match for c in passed)
    return VerifiedClaim(claim.text.strip(), passed, best, verdict.verdict), usage


async def verify_draft(
    draft: AnswerDraft,
    id_map: dict[str, ScoredChunk],
    llm: LLMProvider,
    *,
    quote_match_min: float,
    min_quote_chars: int = 12,
) -> VerificationResult:
    results = await asyncio.gather(
        *(
            _verify_claim(c, id_map, llm, quote_match_min=quote_match_min, min_quote_chars=min_quote_chars)
            for c in draft.claims
        )
    )
    outcome = VerificationResult()
    for claim, usage in results:
        outcome.usage += usage
        if claim is None:
            outcome.dropped += 1
        else:
            outcome.claims.append(claim)
    return outcome
