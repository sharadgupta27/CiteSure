"""Claude via the official Anthropic SDK, using structured outputs (`output_config.format`).

Notes on the current API: Sonnet 5.5 and Haiku 5.5 reject prefill and non-default sampling parameters,
so none are sent. Thinking stays at the model default; `effort` keeps latency and cost in check.
"""

from __future__ import annotations

import json
from typing import Any, cast

import anthropic

from app.config import Settings
from app.llm.base import GenerationRequest, Usage
from app.rag.generation.schema import (
    ANSWER_JSON_SCHEMA,
    CORRECTNESS_JSON_SCHEMA,
    ENTAILMENT_JSON_SCHEMA,
    AnswerDraft,
    CorrectnessVerdict,
    EntailmentVerdict,
)


class ModelRefused(Exception):
    """The model declined to answer (stop_reason == "refusal")."""


class AnthropicProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=3, timeout=60.0)
        self.answer_model = settings.answer_model
        self.verify_model = settings.verify_model
        self._answer_tokens = settings.max_answer_tokens
        self._verify_tokens = settings.max_verify_tokens

    async def _structured(
        self, *, model: str, system: str, user: str, schema: dict[str, Any], max_tokens: int, effort: str
    ) -> tuple[dict[str, Any], Usage]:
        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=cast(Any, {"effort": effort, "format": {"type": "json_schema", "schema": schema}}),
        )
        usage = Usage(response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason == "refusal":
            raise ModelRefused
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("The model did not return valid JSON") from exc
        return data, usage

    async def generate_answer(self, request: GenerationRequest) -> tuple[AnswerDraft, Usage]:
        try:
            data, usage = await self._structured(
                model=self.answer_model,
                system=request.system,
                user=request.user,
                schema=ANSWER_JSON_SCHEMA,
                max_tokens=self._answer_tokens,
                effort="medium",
            )
        except ModelRefused:
            return AnswerDraft(claims=[], refusal="The model declined to answer."), Usage()
        return AnswerDraft.model_validate(data), usage

    async def judge_entailment(
        self, *, system: str, user: str, claim: str, evidence: str
    ) -> tuple[EntailmentVerdict, Usage]:
        try:
            data, usage = await self._structured(
                model=self.verify_model,
                system=system,
                user=user,
                schema=ENTAILMENT_JSON_SCHEMA,
                max_tokens=self._verify_tokens,
                effort="low",
            )
        except ModelRefused:
            return EntailmentVerdict(verdict="unsupported", reason="The verifier declined."), Usage()
        return EntailmentVerdict.model_validate(data), usage

    async def judge_correctness(
        self, *, system: str, question: str, expected: str, actual: str
    ) -> tuple[CorrectnessVerdict, Usage]:
        user = f"Question: {question}\n\nReference answer: {expected}\n\nAnswer to grade: {actual}"
        try:
            data, usage = await self._structured(
                model=self.verify_model,
                system=system,
                user=user,
                schema=CORRECTNESS_JSON_SCHEMA,
                max_tokens=self._verify_tokens,
                effort="low",
            )
        except ModelRefused:
            return CorrectnessVerdict(score=0.0, reason="The judge declined."), Usage()
        data["score"] = min(1.0, max(0.0, float(data["score"])))
        return CorrectnessVerdict.model_validate(data), usage
