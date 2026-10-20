"""MCP server tests with a mocked CiteSure API (no network, no Docker)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from citesure_client import CiteSureClient, CiteSureError  # noqa: E402

WS = "11111111-1111-1111-1111-111111111111"
SECRET_TOKEN = "super-secret-token-value"


def make_backend(routes: dict[tuple[str, str], tuple[int, object]], calls: list[httpx.Request] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if request.url.path.endswith("/auth/login"):
            body = json.loads(request.content)
            ok = body["password"] == "right-password"
            return httpx.Response(200 if ok else 401, json={"access_token": SECRET_TOKEN} if ok else {"detail": "Wrong email or password"})
        key = (request.method, request.url.path.removeprefix("/api/v1"))
        if key == ("GET", "/workspaces"):
            return httpx.Response(200, json=[{"id": WS, "name": "Acme", "role": "member"}])
        status, payload = routes.get(key, (404, {"detail": "not found"}))
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


@pytest.fixture
def use_backend(monkeypatch: pytest.MonkeyPatch):
    def install(routes: dict[tuple[str, str], tuple[int, object]], password: str = "right-password", calls: list[httpx.Request] | None = None) -> None:
        monkeypatch.delenv("CITESURE_WORKSPACE_ID", raising=False)
        server._client = CiteSureClient("http://test", "agent@acme.example", password, transport=make_backend(routes, calls))

    yield install
    server._client = None


async def test_tools_resources_and_prompt_are_registered_and_there_are_no_write_or_delete_tools() -> None:
    tools = {t.name: t for t in await server.mcp.list_tools()}
    assert set(tools) == {"list_collections", "explain_retrieval", "search_corpus", "get_chunk", "ask", "run_eval"}
    assert not [n for n in tools if any(word in n for word in ("delete", "remove", "write", "update", "upload", "create"))]
    for name in ("list_collections", "explain_retrieval", "search_corpus", "get_chunk"):
        assert tools[name].annotations.read_only_hint is True
    assert all(t.annotations.destructive_hint is False for t in tools.values())
    assert [str(getattr(r, "uri_template", r)) for r in await server.mcp.list_resource_templates()] == ["citesure://documents/{document_id}"]
    assert [p.name for p in await server.mcp.list_prompts()] == ["diagnose-bad-answer"]


async def test_list_collections_returns_only_what_the_api_returns(use_backend) -> None:
    use_backend({("GET", f"/workspaces/{WS}/collections"): (200, [{"id": "c1", "name": "General", "visibility": "workspace", "group_ids": [], "created_at": "x"}])})
    result = json.loads(await server.list_collections())
    assert result["workspace_id"] == WS
    assert result["collections"] == [{"id": "c1", "name": "General", "visibility": "workspace"}]


async def test_a_forbidden_chunk_becomes_a_clear_error_not_an_exception(use_backend) -> None:
    use_backend({("GET", "/chunks/secret"): (404, {"detail": "Chunk not found"})})
    result = await server.get_chunk("secret")
    assert result.startswith("ERROR:") and "404" in result
    assert SECRET_TOKEN not in result


async def test_wrong_credentials_never_echo_the_password_or_token(use_backend) -> None:
    use_backend({}, password="the-wrong-password")
    result = await server.list_collections()
    assert result.startswith("ERROR:")
    assert "the-wrong-password" not in result and SECRET_TOKEN not in result


async def test_explain_retrieval_validates_input_and_summarises_each_stage(use_backend) -> None:
    candidate = {"chunk_id": "c1", "document_title": "Parental Leave", "rank": 1, "score": 0.5, "snippet": "16 weeks"}
    trace = {"query": "q", "config": {}, "allowed_collections": 1, "vector": [candidate], "fts": [], "fused": [candidate], "reranked": [candidate]}
    use_backend({("GET", "/retrieval/explain"): (200, trace)})
    assert (await server.explain_retrieval("q", retrieval_mode="nonsense")).startswith("ERROR")
    result = json.loads(await server.explain_retrieval("q"))
    assert result["reranked"][0]["document"] == "Parental Leave" and result["allowed_collections"] == 1


async def test_search_corpus_clips_long_text_and_limits_results(use_backend) -> None:
    hits = [{"chunk_id": f"c{i}", "document_title": "D", "rank": i, "score": 1.0, "snippet": "s"} for i in range(8)]
    trace = {"query": "q", "config": {}, "allowed_collections": 1, "vector": [], "fts": [], "fused": [], "reranked": hits}
    chunk = {"id": "x", "document_title": "D", "heading_path": ["H"], "page_start": None, "text": "word " * 2000}
    routes: dict[tuple[str, str], tuple[int, object]] = {("GET", "/retrieval/explain"): (200, trace)}
    routes |= {("GET", f"/chunks/c{i}"): (200, chunk) for i in range(8)}
    use_backend(routes)
    results = json.loads(await server.search_corpus("q", limit=3))
    assert len(results) == 3
    assert all(len(r["text"]) < 1400 and "more characters" in r["text"] for r in results)
    assert len(json.loads(await server.search_corpus("q", limit=999))) == 8  # capped by what exists, never above 10


async def test_ask_summarises_verified_claims_and_refusals(use_backend) -> None:
    answered = {
        "status": "answered",
        "dropped_claims": 1,
        "latency_ms_by_stage": {"verify": 3.0},
        "refusal": None,
        "claims": [{"text": "16 weeks.", "verification": {"quote_match": 1, "entailment": "supported"}, "citations": [{"chunk_id": "c1", "document_title": "Leave", "quote": "16 weeks", "quote_start": 0}]}],
    }
    use_backend({("POST", "/ask"): (200, answered)})
    result = json.loads(await server.ask("how long?"))
    assert result["claims"][0]["citations"][0]["document"] == "Leave" and result["dropped_claims"] == 1
    refused = {"status": "refused", "dropped_claims": 0, "latency_ms_by_stage": {}, "claims": [], "refusal": {"reason": "no_sources", "message": "none", "closest_sources": []}}
    use_backend({("POST", "/ask"): (200, refused)})
    assert json.loads(await server.ask("x?"))["refusal"]["reason"] == "no_sources"


async def test_run_eval_needs_an_admin_and_reports_a_permission_error_otherwise(use_backend) -> None:
    use_backend({("POST", f"/workspaces/{WS}/eval-runs"): (403, {"detail": "Only workspace admins can do this"})})
    result = await server.run_eval("check")
    assert result.startswith("ERROR:") and "403" in result and "admins" in result


async def test_run_eval_returns_metrics_when_finished(use_backend) -> None:
    run = {"id": "r1", "status": "queued"}
    done = {"id": "r1", "status": "done", "error": None, "metrics": {"mrr": 0.9}, "items": [{"question": "Q1?", "answerable": True, "answer_status": "refused"}]}
    use_backend({("POST", f"/workspaces/{WS}/eval-runs"): (202, run), ("GET", "/eval-runs/r1"): (200, done)})
    result = json.loads(await server.run_eval("check", top_k=500))
    assert result["metrics"] == {"mrr": 0.9} and result["answerable_but_refused"] == ["Q1?"]


async def test_the_client_logs_in_again_once_when_the_token_expires() -> None:
    state = {"logins": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            state["logins"] += 1
            return httpx.Response(200, json={"access_token": f"token-{state['logins']}"})
        if request.headers["authorization"] == "Bearer token-1":
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(200, json=[{"id": WS}])

    client = CiteSureClient("http://test", "a@b.co", "pw", transport=httpx.MockTransport(handler))
    assert await client.request("GET", "/workspaces") == [{"id": WS}]
    assert state["logins"] == 2


async def test_missing_password_is_a_clear_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CITESURE_MCP_PASSWORD", raising=False)
    with pytest.raises(CiteSureError, match="CITESURE_MCP_PASSWORD"):
        CiteSureClient.from_env()


def test_the_diagnose_prompt_forbids_editing_the_golden_set() -> None:
    text = server.diagnose_bad_answer("How many weeks?", "16", "8")
    assert "How many weeks?" in text and "Do not edit evaluation data" in text and "explain_retrieval" in text
