"""The LLM boundary. Only this package imports the Anthropic SDK. The generation and verification models are
never given tools: they receive text and return structured JSON, nothing else (non-negotiable 3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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


class LLMProvider(Protocol):
    answer_model: str
    verify_model: str

    async def generate_answer(self, request: GenerationRequest) -> tuple[AnswerDraft, Usage]: ...

    async def judge_entailment(
        self, *, system: str, user: str, claim: str, evidence: str
    ) -> tuple[EntailmentVerdict, Usage]: ...

    async def judge_correctness(
        self, *, system: str, question: str, expected: str, actual: str
    ) -> tuple[CorrectnessVerdict, Usage]: ...
