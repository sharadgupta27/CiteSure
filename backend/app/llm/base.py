"""The LLM boundary. The Anthropic SDK is imported only by llm/anthropic_provider.py and by research/web.py (URL discovery
for the public lane, which receives only the egress-guarded keyword query). The generation and verification models are
never given tools: they receive text and return structured JSON, nothing else (non-negotiable 3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from app.rag.generation.prompt import SourceBlock
from app.rag.generation.schema import AnswerDraft, CorrectnessVerdict, EntailmentVerdict


@dataclass(frozen=True)
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(self.tokens_in + other.tokens_in, self.tokens_out + other.tokens_out)


@dataclass(frozen=True)
class GenerationRequest:
    system: str
    user: str  # the fully rendered user message (sources + question)
    question: str
    sources: list[SourceBlock]
    # What the caller wants. Real models learn this from `system`; the offline fake has no prompt to read, so it uses it.
    task: Literal["answer", "summary", "compare"] = "answer"


class LLMProvider(Protocol):
    hosted: bool  # True when the model runs on someone else's servers: it may then read public text only (private mode)
    answer_model: str
    verify_model: str

    async def generate_answer(self, request: GenerationRequest) -> tuple[AnswerDraft, Usage]: ...

    async def judge_entailment(
        self, *, system: str, user: str, claim: str, evidence: str
    ) -> tuple[EntailmentVerdict, Usage]: ...

    async def judge_correctness(
        self, *, system: str, question: str, expected: str, actual: str
    ) -> tuple[CorrectnessVerdict, Usage]: ...
