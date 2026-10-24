"""Private mode: the local model provider, the boot-time invariants, and which model reads which text."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from app.config import Settings, is_private_url
from app.embeddings.fake import FakeEmbedder, LexicalReranker
from app.llm.base import GenerationRequest
from app.llm.fake import FakeProvider
from app.llm.local_provider import LocalModelError, LocalProvider, parse_json_object
from app.providers import Providers
from app.rag.generation.prompt import SourceBlock
from app.rag.types import ScoredChunk
from app.services.pipeline import PrivacyViolation, choose_llm, ensure_lane_safe


def reply(content: str, prompt: int = 11, completion: int = 7) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
        },
    )


def provider(handler: Any, **settings: Any) -> LocalProvider:
    return LocalProvider(Settings(env="test", llm_provider="local", **settings), transport=httpx.MockTransport(handler))


REQUEST = GenerationRequest(system="sys", user="usr", question="q", sources=[SourceBlock("S1", "Doc", "H", "text")])
ANSWER = {"claims": [{"text": "A fact.", "citations": [{"source_id": "S1", "quote": "text"}]}], "refusal": None}


def test_json_extraction_accepts_fences_and_think_blocks() -> None:
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('<think>hmm {"x": 0}</think>\n{"a": 2}') == {"a": 2}
    for bad in ("no json here", "[1, 2]", ""):
        with pytest.raises(ValueError):
            parse_json_object(bad)


async def test_answer_request_shape_and_usage() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return reply(json.dumps(ANSWER))

    llm = provider(handler, local_llm_base_url="http://ollama:11434/v1/", local_answer_model="m-answer")
    draft, usage = await llm.generate_answer(REQUEST)
    assert draft.claims[0].citations[0].source_id == "S1" and (usage.tokens_in, usage.tokens_out) == (11, 7)
    body = seen[0]
    assert body["model"] == "m-answer" and body["temperature"] == 0 and body["stream"] is False
    assert body["response_format"]["type"] == "json_schema"
    assert "JSON Schema" in body["messages"][0]["content"] and body["messages"][1]["content"] == "usr"


async def test_requests_go_only_to_the_configured_local_server() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return reply(json.dumps(ANSWER))

    await provider(handler, local_llm_base_url="http://ollama:11434/v1").generate_answer(REQUEST)
    assert hosts == ["ollama"]


async def test_a_runtime_without_schema_support_falls_back_to_json_mode() -> None:
    formats: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        formats.append(body["response_format"]["type"])
        return httpx.Response(400) if body["response_format"]["type"] == "json_schema" else reply(json.dumps(ANSWER))

    await provider(handler).generate_answer(REQUEST)
    assert formats == ["json_schema", "json_object"]


async def test_one_malformed_reply_is_retried_then_the_call_fails_closed() -> None:
    replies = iter(["not json", json.dumps(ANSWER)])
    draft, _ = await provider(lambda r: reply(next(replies))).generate_answer(REQUEST)
    assert draft.claims

    with pytest.raises(LocalModelError) as caught:
        await provider(lambda r: reply("still not json")).generate_answer(REQUEST)
    assert "still not json" not in str(caught.value)  # model output may echo documents; it is never put in errors

    with pytest.raises(LocalModelError):
        await provider(lambda r: httpx.Response(500)).generate_answer(REQUEST)


async def test_an_answer_in_the_wrong_shape_is_an_error_not_a_guess() -> None:
    with pytest.raises(LocalModelError):
        await provider(lambda r: reply(json.dumps({"claims": "nope"}))).generate_answer(REQUEST)


async def test_an_unreadable_verdict_never_counts_as_support() -> None:
    llm = provider(lambda r: reply(json.dumps({"verdict": "definitely", "reason": ""})))
    verdict, _ = await llm.judge_entailment(system="s", user="u", claim="c", evidence="e")
    assert verdict.verdict == "unsupported"
    judged, _ = await llm.judge_correctness(system="s", question="q", expected="e", actual="a")
    assert judged.score == 0.0


async def test_verdicts_are_parsed() -> None:
    llm = provider(lambda r: reply(json.dumps({"verdict": "supported", "reason": "ok"})))
    assert (await llm.judge_entailment(system="s", user="u", claim="c", evidence="e"))[0].verdict == "supported"


# --- boot-time invariants ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "private"),
    [
        ("http://localhost:11434/v1", True),
        ("http://127.0.0.1:8000/v1", True),
        ("http://10.0.0.7:8000/v1", True),
        ("http://ollama:11434/v1", True),
        ("http://gpu-box.lan:8000/v1", True),
        ("http://api.openai.com/v1", False),
        ("https://my-llm.example.com/v1", False),
        ("http://8.8.8.8/v1", False),
        ("", False),
    ],
)
def test_private_url_detection(url: str, private: bool) -> None:
    assert is_private_url(url) is private


def test_private_mode_refuses_a_hosted_internal_model() -> None:
    with pytest.raises(RuntimeError, match="hosted model"):
        Settings(env="test", private_mode=True, llm_provider="anthropic").assert_private_mode_consistent()
    with pytest.raises(RuntimeError, match="hosted API"):
        Settings(env="test", private_mode=True, embedding_provider="voyage").assert_private_mode_consistent()


def test_private_mode_refuses_a_local_model_at_a_public_address() -> None:
    bad = Settings(env="test", private_mode=True, llm_provider="local", local_llm_base_url="https://llm.example.com/v1")
    with pytest.raises(RuntimeError, match="private network"):
        bad.assert_private_mode_consistent()
    Settings(env="test", private_mode=True, llm_provider="local").assert_private_mode_consistent()


def test_private_mode_in_prod_needs_the_egress_proxy_when_the_public_lane_is_on() -> None:
    base: dict[str, Any] = {"env": "prod", "private_mode": True, "public_research_enabled": True, "jwt_secret": "x" * 40}
    with pytest.raises(RuntimeError, match="EGRESS_PROXY_URL"):
        Settings(**base).assert_safe_for_prod()
    Settings(**base, egress_proxy_url="http://egress-proxy:3128").assert_safe_for_prod()
    Settings(env="prod", private_mode=True, jwt_secret="x" * 40).assert_safe_for_prod()  # no public lane, no proxy needed


def test_public_settings_need_the_lane_to_be_enabled() -> None:
    with pytest.raises(RuntimeError, match="PUBLIC_RESEARCH_ENABLED"):
        Settings(env="test", public_llm_provider="anthropic").assert_private_mode_consistent()
    with pytest.raises(RuntimeError, match="PUBLIC_RESEARCH_ENABLED"):
        Settings(env="test", default_scope="both").assert_private_mode_consistent()
    with pytest.raises(RuntimeError, match="web"):
        Settings(env="test", public_research_enabled=True, egress_mode="open").assert_private_mode_consistent()


# --- which model reads which text --------------------------------------------------------------------------------------
class HostedFake(FakeProvider):
    hosted = True


def providers(public: FakeProvider | None) -> Providers:
    return Providers(FakeProvider(), FakeEmbedder(), LexicalReranker(), blobs=None, public_llm=public)  # type: ignore[arg-type]


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


def test_company_text_always_goes_to_the_internal_model() -> None:
    p = providers(HostedFake())
    assert choose_llm(p, internal_text=True, question_cleared=True) is p.llm


def test_public_only_text_goes_to_the_hosted_model_only_when_the_question_was_cleared() -> None:
    public = HostedFake()
    p = providers(public)
    assert choose_llm(p, internal_text=False, question_cleared=True) is public
    assert choose_llm(p, internal_text=False, question_cleared=False) is p.llm  # an uncleared question stays local
    assert choose_llm(providers(None), internal_text=False, question_cleared=True) is not public


def test_the_safety_net_refuses_company_text_for_a_hosted_model_in_private_mode() -> None:
    private = Settings(env="test", private_mode=True)
    with pytest.raises(PrivacyViolation):
        ensure_lane_safe(private, HostedFake(), [chunk("internal"), chunk("public")])
    ensure_lane_safe(private, HostedFake(), [chunk("public")])  # public text is fine
    ensure_lane_safe(private, FakeProvider(), [chunk("internal")])  # a local model may read company text
    ensure_lane_safe(Settings(env="test"), HostedFake(), [chunk("internal")])  # outside private mode: the operator's call
