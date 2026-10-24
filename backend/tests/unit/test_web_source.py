"""The open-web source: Claude's search tool finds URLs, our fetcher reads the pages. No network, no API key."""

from __future__ import annotations

from types import SimpleNamespace

import httpx

from app.egress.client import EgressClient
from app.research.web import WebHit, hits_from_response, passages_for

PAGE = (
    b"""<html><head><title>Sparse attention explained</title></head><body>
<h1>Sparse attention explained</h1>
<p>Block-sparse attention reduces memory use for long sequences by skipping most query-key pairs.</p>
<h2>Cooking</h2><p>__COOKING__</p>
</body></html>"""
).replace(b"__COOKING__", b"Add two cups of flour and stir until smooth. " * 80)


def result(url: str, title: str = "T") -> SimpleNamespace:
    return SimpleNamespace(type="web_search_result", url=url, title=title)


def test_hits_are_collected_from_search_result_blocks_only() -> None:
    blocks = [
        SimpleNamespace(type="text", text="I searched."),
        SimpleNamespace(type="web_search_tool_result", content=[result("https://a.org/x", "A"), result("https://a.org/x")]),
        SimpleNamespace(
            type="web_search_tool_result", content=[result("http://insecure.org/y"), result("https://b.org/z", "B")]
        ),
    ]
    hits = hits_from_response(blocks, limit=5)
    assert [h.url for h in hits] == ["https://a.org/x", "https://b.org/z"]  # de-duplicated, https only
    assert len(hits_from_response(blocks, limit=1)) == 1


def test_a_search_error_object_is_skipped_not_iterated() -> None:
    error = SimpleNamespace(type="web_search_tool_result_error", error_code="max_uses_exceeded")
    blocks = [SimpleNamespace(type="web_search_tool_result", content=error)]
    assert hits_from_response(blocks, limit=5) == []


def web_client(handler: httpx.MockTransport) -> EgressClient:
    return EgressClient(
        mode="open", allow_hosts=[], user_agent="t", timeout_s=5, max_bytes=200_000, check_dns=False, transport=handler
    )


async def test_pages_are_fetched_and_only_relevant_passages_are_kept() -> None:
    client = web_client(
        httpx.MockTransport(lambda r: httpx.Response(200, content=PAGE, headers={"content-type": "text/html"}))
    )
    papers = await passages_for(client, WebHit("https://example.org/sparse", "Sparse"), "sparse attention memory sequences")
    assert papers and all(p.source == "web" and p.url == "https://example.org/sparse" for p in papers)
    assert papers[0].title == "Sparse attention explained"
    assert "block-sparse attention" in papers[0].text.lower()
    assert all("block-sparse" in p.text.lower() for p in papers)  # passages that never mention the topic are not quoted


async def test_a_failing_or_non_document_page_yields_nothing() -> None:
    for response in (
        httpx.Response(404),
        httpx.Response(200, content=b"\x00\x01\x02binary"),
        httpx.Response(200, content=b"<html><body></body></html>"),
    ):
        client = web_client(httpx.MockTransport(lambda r, response=response: response))
        assert await passages_for(client, WebHit("https://example.org/x", "X"), "sparse attention") == []


async def test_a_page_on_a_private_address_is_never_fetched() -> None:
    calls: list[httpx.Request] = []
    client = web_client(httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, content=PAGE)))
    assert await passages_for(client, WebHit("https://10.0.0.5/admin", "Admin"), "sparse attention") == []
    assert calls == []
