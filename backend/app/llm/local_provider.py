"""A model that runs on this machine or a private network, for the INTERNAL lane.

Speaks the OpenAI-style `/chat/completions` protocol, which Ollama, vLLM, llama.cpp's server and LM Studio all
implement, so the operator picks the runtime. This is the only provider that may read company documents in private
mode. It never goes through a proxy and never uses ambient proxy settings: the request must reach the local server
directly, and nowhere else.

Small local models are less reliable at structured output than hosted ones, so the schema is repeated in the system
message, the server is asked to constrain decoding to it, and one malformed reply is retried before failing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from pydantic import ValidationError

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

log = logging.getLogger("citesure.llm.local")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
RETRIES = 1


class LocalModelError(RuntimeError):
    """The local model server failed or kept returning unusable output. The message never contains document text."""


def parse_json_object(text: str) -> dict[str, Any]:
    """Models sometimes wrap JSON in code fences or a <think> block; accept both, nothing else."""
    cleaned = _FENCE.sub("", _THINK.sub("", text).strip()).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in the reply")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("the reply is not a JSON object")
    return data


class LocalProvider:
    hosted = False

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.answer_model = settings.local_answer_model
        self.verify_model = settings.local_verify_model
        self._url = settings.local_llm_base_url.rstrip("/") + "/chat/completions"
        self._answer_tokens = settings.max_answer_tokens
        self._verify_tokens = settings.max_verify_tokens
        self._client = httpx.AsyncClient(timeout=settings.local_llm_timeout_s, trust_env=False, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _complete(
        self, *, model: str, system: str, user: str, schema: dict[str, Any], name: str, max_tokens: int
    ) -> tuple[dict[str, Any], Usage]:
        system_with_schema = f"{system}\n\nReply with ONE JSON object only, matching this JSON Schema:\n{json.dumps(schema)}"
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system_with_schema}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
        }
        usage = Usage()
        last_error = "no attempt"
        for attempt in range(RETRIES + 1):
            try:
                response = await self._client.post(self._url, json=body)
                if response.status_code == 400 and "response_format" in body:
                    body["response_format"] = {"type": "json_object"}  # the runtime lacks schema-constrained decoding
                    response = await self._client.post(self._url, json=body)
                response.raise_for_status()
                payload = response.json()
                usage += Usage(
                    int(payload.get("usage", {}).get("prompt_tokens", 0)),
                    int(payload.get("usage", {}).get("completion_tokens", 0)),
                )
                return parse_json_object(payload["choices"][0]["message"]["content"] or ""), usage
            except httpx.HTTPError as exc:
                last_error = f"server error: {type(exc).__name__}"
            except (KeyError, IndexError, ValueError) as exc:
                last_error = f"unusable reply: {type(exc).__name__}"
            log.warning("local model attempt %d failed (%s)", attempt + 1, last_error)
        raise LocalModelError(f"The local model failed: {last_error}")

    async def generate_answer(self, request: GenerationRequest) -> tuple[AnswerDraft, Usage]:
        data, usage = await self._complete(
            model=self.answer_model,
            system=request.system,
            user=request.user,
            schema=ANSWER_JSON_SCHEMA,
            name="answer",
            max_tokens=self._answer_tokens,
        )
        try:
            return AnswerDraft.model_validate(data), usage
        except ValidationError as exc:
            raise LocalModelError("The local model returned an answer in the wrong shape") from exc

    async def judge_entailment(
        self, *, system: str, user: str, claim: str, evidence: str
    ) -> tuple[EntailmentVerdict, Usage]:
        data, usage = await self._complete(
            model=self.verify_model,
            system=system,
            user=user,
            schema=ENTAILMENT_JSON_SCHEMA,
            name="entailment",
            max_tokens=self._verify_tokens,
        )
        try:
            return EntailmentVerdict.model_validate(data), usage
        except ValidationError:
            # An unreadable verdict must never count as support: the claim is dropped.
            return EntailmentVerdict(verdict="unsupported", reason="The verifier returned an unreadable verdict."), usage

    async def judge_correctness(
        self, *, system: str, question: str, expected: str, actual: str
    ) -> tuple[CorrectnessVerdict, Usage]:
        user = f"<question>\n{question}\n</question>\n<reference>\n{expected}\n</reference>\n<answer>\n{actual}\n</answer>"
        data, usage = await self._complete(
            model=self.verify_model,
            system=system,
            user=user,
            schema=CORRECTNESS_JSON_SCHEMA,
            name="correctness",
            max_tokens=self._verify_tokens,
        )
        try:
            verdict = CorrectnessVerdict.model_validate(data)
        except ValidationError:
            return CorrectnessVerdict(score=0.0, reason="The judge returned an unreadable verdict."), usage
        return verdict, usage
