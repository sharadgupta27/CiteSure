"""Verification stage 2: does the evidence actually support the claim? (A cheaper LLM judges.)

Stage 1 proves the quote exists; stage 2 catches 'real quote, wrong conclusion'."""

from __future__ import annotations

from app.llm.base import LLMProvider, Usage
from app.rag.generation.prompt import ENTAILMENT_PROMPT, load_prompt, render_entailment_message
from app.rag.generation.schema import EntailmentVerdict
from app.rag.types import ScoredChunk

WINDOW_CHARS = 600


def evidence_window(chunk: ScoredChunk, quote_start: int, quote_end: int) -> str:
    """The quoted span plus some surrounding text, so the judge sees conditions like 'only if...' next to it."""
    start = max(0, quote_start - WINDOW_CHARS)
    end = min(len(chunk.text), quote_end + WINDOW_CHARS)
    return chunk.text[start:end]


async def check_entailment(llm: LLMProvider, claim: str, evidence: str) -> tuple[EntailmentVerdict, Usage]:
    return await llm.judge_entailment(
        system=load_prompt(ENTAILMENT_PROMPT),
        user=render_entailment_message(claim, evidence),
        claim=claim,
        evidence=evidence,
    )
