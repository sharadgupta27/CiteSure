"""The OpenAI provider: what it sends, how it handles refusals, and which lane it may serve.

No real API is called: every request goes to an httpx MockTransport."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.llm import build_llm, build_public_llm
from app.llm.base import GenerationRequest
from app.llm.local_provider import LocalModelError
from app.llm.openai_provider import OpenAIProvider
from app.rag.generation.prompt import SourceBlock
from app.rag.types import ScoredChunk
from app.services.pipeline import PrivacyViolation, ensure_lane_safe

KEY = "sk-test-not-a-real-key"
REQUEST = GenerationRequest(system="sys", user="usr", question="q", sources=[SourceBlock("S1", "Doc", "H", "text")])
ANSWER = {"claims": [{"text": "A fact.", "citations": [{"source_id": "S1", "quote": "text"}]}], "refusal": None}


def reply(message: dict[str, Any], prompt: int = 13, completion: int = 5) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": message}], "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}
    )


def provider(handler: Any, **settings: Any) -> OpenAIProvider:
    return OpenAIProvider(Settings(env="test", openai_api_key=KEY, **settings), transport=httpx.MockTransport(handler))


async def test_answer_request_goes_to_openai_with_the_key_and_a_strict_schema() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return reply({"content": json.dumps(ANSWER)})

    draft, usage = await provider(handler, openai_answer_model="gpt-answer").generate_answer(REQUEST)
    assert draft.claims[0].citations[0].source_id == "S1"
    assert (usage.tokens_in, usage.tokens_out) == (13, 5)
    request = seen[0]
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == "gpt-answer" and body["temperature"] == 0
    assert "max_completion_tokens" in body and "max_tokens" not in body
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


async def test_the_verifier_uses_the_verify_model() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return reply({"content": json.dumps({"verdict": "supported", "reason": "quoted"})})

    verdict, _ = await provider(handler, openai_verify_model="gpt-verify").judge_entailment(
        system="s", user="u", claim="c", evidence="e"
    )
    assert verdict.verdict == "supported" and seen[0]["model"] == "gpt-verify"


async def test_a_refusal_becomes_a_refused_answer_or_an_unsupported_verdict_without_retrying() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return reply({"content": None, "refusal": "I can't help with that."})

    llm = provider(handler)
    draft, _ = await llm.generate_answer(REQUEST)
    assert draft.claims == [] and draft.refusal
    assert calls == 1
    verdict, _ = await llm.judge_entailment(system="s", user="u", claim="c", evidence="e")
    assert verdict.verdict == "unsupported"  # a declined check never counts as support
    correctness, _ = await llm.judge_correctness(system="s", question="q", expected="e", actual="a")
    assert correctness.score == 0.0


async def test_api_errors_fail_with_a_message_that_names_openai_and_holds_no_document_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    with pytest.raises(LocalModelError, match="OpenAI model") as excinfo:
        await provider(handler).generate_answer(REQUEST)
    assert "usr" not in str(excinfo.value) and KEY not in str(excinfo.value)


def test_a_key_is_required() -> None:
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIProvider(Settings(env="test"))


def test_both_lanes_can_be_built_and_the_model_is_marked_hosted() -> None:
    internal = build_llm(Settings(env="test", llm_provider="openai", openai_api_key=KEY))
    public = build_public_llm(
        Settings(env="test", public_research_enabled=True, public_llm_provider="openai", openai_api_key=KEY)
    )
    assert isinstance(internal, OpenAIProvider) and isinstance(public, OpenAIProvider)
    assert internal.hosted and public.hosted


def test_private_mode_refuses_openai_for_company_text_but_allows_it_for_the_public_lane() -> None:
    with pytest.raises(RuntimeError, match="hosted model"):
        Settings(env="test", private_mode=True, llm_provider="openai").assert_private_mode_consistent()
    Settings(
        env="test", private_mode=True, llm_provider="local", public_research_enabled=True, public_llm_provider="openai"
    ).assert_private_mode_consistent()


def test_the_safety_net_never_lets_openai_read_company_text_in_private_mode() -> None:
    def chunk(kind: str) -> ScoredChunk:
        return ScoredChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            document_title="t",
            collection_id=uuid.uuid4(),
            ord=0,
            text="x",
            heading_path=[],
            page_start=None,
            page_end=None,
            char_start=0,
            char_end=1,
            source_type=kind,  # type: ignore[arg-type]
        )

    llm = OpenAIProvider(Settings(env="test", openai_api_key=KEY))
    with pytest.raises(PrivacyViolation):
        ensure_lane_safe(Settings(env="test", private_mode=True), llm, [chunk("internal")])
    ensure_lane_safe(Settings(env="test", private_mode=True), llm, [chunk("public")])


def test_openai_is_on_the_egress_allow_list() -> None:
    assert "api.openai.com" in Settings(env="test").egress_allow_hosts.split(",")
