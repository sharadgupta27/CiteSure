"""The open-web source: Claude's web search tool finds URLs, our own fetcher reads the pages.

Why two steps: the search tool runs on Anthropic's servers and only ever receives the guarded keyword query. We then
fetch the pages ourselves, through the egress client, so the passages we quote are the real page text (verifiable
by the same quote check as any document) and not a model's paraphrase of it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import anthropic
from anthropic.types import WebSearchTool20260209Param

from app.config import Settings
from app.egress import EgressClient, EgressDenied
from app.errors import AppError
from app.rag.chunking.chunker import chunk_sections
from app.rag.parsing import ParseError, detect, parse_document
from app.rag.text import content_terms
from app.research.papers import Paper

log = logging.getLogger("citesure.research.web")

WEB_TOOL: Literal["web_search_20260209"] = "web_search_20260209"
PASSAGE_TOKENS = 250
PASSAGES_PER_PAGE = 2
MIN_OVERLAP = 0.25
FETCHABLE = {"html", "pdf"}


@dataclass(frozen=True)
class WebHit:
    url: str
    title: str


class WebDiscovery(Protocol):
    async def discover(self, query: str) -> list[WebHit]: ...


class AnthropicWebDiscovery:
    """Asks Claude to run the web search tool for the query. The model sees the query and nothing else."""

    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for the web source")
        extra: dict[str, Any] = {"proxy": settings.egress_proxy_url, "trust_env": False} if settings.egress_proxy_url else {}
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            max_retries=2,
            timeout=60.0,
            http_client=anthropic.DefaultAsyncHttpxClient(**extra),
        )
        self._model = settings.web_search_model or settings.answer_model
        self._max_uses = settings.web_search_max_uses
        self._limit = settings.web_fetch_pages

    async def discover(self, query: str) -> list[WebHit]:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            tools=[WebSearchTool20260209Param(type=WEB_TOOL, name="web_search", max_uses=self._max_uses)],
            messages=[
                {
                    "role": "user",
                    "content": "Search the web for authoritative published sources (peer-reviewed papers, preprints, "
                    f"official reports, reputable journalism) about: {query}\nDo not answer; only search.",
                }
            ],
        )
        return hits_from_response(response.content, self._limit)


def hits_from_response(content: list[Any], limit: int) -> list[WebHit]:
    """Collect result URLs from `web_search_tool_result` blocks. A failed search comes back as an error object
    instead of a list (HTTP 200), so branch on the type before iterating."""
    hits: dict[str, WebHit] = {}
    for block in content:
        if getattr(block, "type", "") != "web_search_tool_result":
            continue
        results = getattr(block, "content", None)
        if not isinstance(results, list):
            log.warning("web search returned an error object")
            continue
        for item in results:
            url = getattr(item, "url", "") or ""
            if url.startswith("https://") and url not in hits:
                hits[url] = WebHit(url=url, title=getattr(item, "title", "") or url)
    return list(hits.values())[:limit]


async def passages_for(client: EgressClient, hit: WebHit, query: str) -> list[Paper]:
    """Fetch one page and return the passages that best match the query. Any failure just means no passages."""
    try:
        response = await client.get("web", hit.url, fingerprint_of=query)
        if response.status != 200:
            return []
        detected = detect(response.content)
        if detected.kind not in FETCHABLE:
            return []
        parsed = parse_document(detected.kind, response.content, hit.url.rsplit("/", 1)[-1] or "page")
    except (EgressDenied, ParseError, AppError, OSError, ValueError, UnicodeDecodeError) as exc:
        log.info("web page skipped: %s", type(exc).__name__)
        return []
    except Exception as exc:  # httpx has its own error tree; one bad page must not fail the answer
        log.info("web page skipped: %s", type(exc).__name__)
        return []
    wanted = set(content_terms(query))
    if not wanted:
        return []
    _, chunks = chunk_sections(parsed.sections, target_tokens=PASSAGE_TOKENS, overlap=0.0)
    scored = sorted(
        ((len(wanted & set(content_terms(c.text))) / len(wanted), c.text) for c in chunks), key=lambda pair: -pair[0]
    )
    title = parsed.title or hit.title
    return [
        Paper(source="web", title=title, text=text, url=hit.url)
        for score, text in scored[:PASSAGES_PER_PAGE]
        if score >= MIN_OVERLAP
    ]
