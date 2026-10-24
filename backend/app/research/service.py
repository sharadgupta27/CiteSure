"""The public research lane, end to end: guard -> keyword query -> connectors -> fuse -> rerank.

Nothing here reads company documents except through the guard's yes/no questions. The result carries passages from the
public internet, an honest record of what was sent where, and user-facing notices when part of the lane was skipped.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.config import Settings
from app.egress import Decision, EgressClient, EgressDenied, EgressGuard, InternalCorpus
from app.embeddings.base import Reranker
from app.rag.retrieval.fusion import reciprocal_rank_fusion
from app.rag.retrieval.rerank import rerank
from app.rag.types import ScoredChunk
from app.research.connectors import Connector, build_connectors
from app.research.papers import EgressRecord, Paper, ResearchResult
from app.research.query import build_public_query
from app.research.web import WebDiscovery, passages_for

if TYPE_CHECKING:
    from app.llm.base import LLMProvider

log = logging.getLogger("citesure.research")

# Reasons about the SENTENCE form of the question. The keyword query drops that form and is checked again on its own,
# so these alone do not stop a search. Anything else (personal data, secrets, deny terms) does.
SOFT_REASONS = frozenset({"copied_from_documents", "too_long"})

# Reasons that come from comparing the text with the company's documents or lists. What a user is told about them is
# deliberately vague: "this phrase exists in a document" is itself information, and a user could use the check to probe
# for sentences in collections they may not read. The precise codes stay in the server logs and metrics.
COMPANY_REASONS = frozenset({"deny_term", "canary", "internal_name", "copied_from_documents"})
COMPANY_CONTENT = "company_content"

_REASON_TEXT = {
    "empty": "there was nothing to search for",
    "too_long": "the query was too long",
    "internal_address": "it mentions an internal address",
    "confidential_marker": "it carries a confidentiality marker",
    COMPANY_CONTENT: "it appears to contain company-sensitive content",
}


def public_reasons(reasons: tuple[str, ...]) -> tuple[str, ...]:
    """The reason codes a user may see: company-derived ones collapse into one."""
    return tuple(dict.fromkeys(COMPANY_CONTENT if r in COMPANY_REASONS else r for r in reasons))


def explain(decision: Decision) -> str:
    parts: list[str] = []
    for reason in public_reasons(decision.reasons):
        if reason.startswith("pii:"):
            parts.append("it contains personal data")
        elif reason.startswith("secret:"):
            parts.append("it looks like it contains a credential")
        else:
            parts.append(_REASON_TEXT.get(reason, "it did not pass the egress check"))
    return "; ".join(dict.fromkeys(parts))


@dataclass(frozen=True)
class Preview:
    query: str
    allowed: bool
    reasons: tuple[str, ...]
    explanation: str


class ResearchKit:
    """Built once at startup: the HTTP gateway, the connectors and (optionally) web discovery and the public model."""

    def __init__(
        self,
        settings: Settings,
        client: EgressClient,
        connectors: list[Connector],
        web: WebDiscovery | None = None,
        public_llm: LLMProvider | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.connectors = connectors
        self.web = web
        self.public_llm = public_llm

    def for_request(self, corpus: InternalCorpus | None) -> PublicResearch:
        return PublicResearch(self, EgressGuard(self.settings, corpus))

    async def aclose(self) -> None:
        await self.client.aclose()


def build_kit(settings: Settings, public_llm: LLMProvider | None = None) -> ResearchKit | None:
    if not settings.public_research_enabled:
        return None
    sources = settings.public_source_list
    client = EgressClient(
        mode=settings.egress_mode,
        allow_hosts=settings.egress_allow_host_list,
        user_agent=settings.public_user_agent,
        timeout_s=settings.public_timeout_s,
        max_bytes=settings.public_max_bytes,
        proxy_url=settings.egress_proxy_url,
    )
    web: WebDiscovery | None = None
    if "web" in sources and settings.public_llm_provider == "anthropic":
        from app.research.web import AnthropicWebDiscovery

        web = AnthropicWebDiscovery(settings)
    return ResearchKit(settings, client, build_connectors(sources, settings.contact_email), web, public_llm)


class PublicResearch:
    def __init__(self, kit: ResearchKit, guard: EgressGuard) -> None:
        self._kit = kit
        self._guard = guard

    async def _decide(self, question: str, explicit_query: str | None) -> tuple[str, Decision, bool]:
        """The query that would be sent, the guard's verdict on it, and whether the whole question is cleared.
        Without an explicit query the question's own blockers (personal data, secrets, deny terms) also stop the
        search, because the keywords are taken from it."""
        question_decision = await self._guard.check(question, kind="question")
        explicit = (explicit_query or "").strip()
        query = explicit or build_public_query(question)
        decision = await self._guard.check(query, kind="query") if query else Decision(False, ("empty",))
        if not explicit:
            blocking = tuple(r for r in question_decision.reasons if r not in SOFT_REASONS)
            if blocking:
                decision = Decision(False, tuple(dict.fromkeys([*blocking, *decision.reasons])))
        return query, decision, question_decision.allowed

    async def preview(self, question: str, explicit_query: str | None = None) -> Preview:
        """What would be sent, and would the guard allow it. Sends nothing."""
        query, decision, _ = await self._decide(question, explicit_query)
        return Preview(
            query=query, allowed=decision.allowed, reasons=public_reasons(decision.reasons), explanation=explain(decision)
        )

    async def search(
        self, question: str, *, explicit_query: str | None = None, reranker: Reranker | None = None
    ) -> ResearchResult:
        result = ResearchResult()
        query, decision, result.question_cleared = await self._decide(question, explicit_query)
        if not decision.allowed:
            return self._blocked(result, decision)

        result.query = query
        per_source = self._kit.settings.public_results_per_source
        tasks = [self._run_source(c.name, c.search(self._kit.client, query, per_source)) for c in self._kit.connectors]
        if self._kit.web is not None:
            tasks.append(self._run_source("web", self._web(query)))
        outcomes = await asyncio.gather(*tasks)

        rankings: list[list[ScoredChunk]] = []
        failed: list[str] = []
        for name, papers, error in outcomes:
            if error is not None:
                failed.append(name)
                result.records.append(EgressRecord(destination=name, status="failed", reason=error))
                continue
            result.records.append(EgressRecord(destination=name, status="sent", query=query))
            rankings.append(self._chunks(papers))
        if failed:
            result.notices.append(f"Some public sources did not respond: {', '.join(failed)}.")

        fused = reciprocal_rank_fusion(rankings)
        top_k = self._kit.settings.public_top_k
        if reranker is not None and fused:
            fused = await rerank(reranker, question, fused[: top_k * 3], top_k)
        result.chunks = fused[:top_k]
        if not result.chunks and not failed:
            result.notices.append("No published sources matched the public search.")
        return result

    def _blocked(self, result: ResearchResult, decision: Decision) -> ResearchResult:
        reasons = ",".join(public_reasons(decision.reasons)) or "blocked"
        result.records.append(EgressRecord(destination="public", status="blocked", reason=reasons))
        result.notices.append(
            f"The public search was skipped because {explain(decision)}. Rephrase the question without internal details, "
            "or edit the public query, and ask again."
        )
        return result

    @staticmethod
    def _chunks(papers: list[Paper]) -> list[ScoredChunk]:
        """One chunk per paper; several passages of one web page get consecutive positions so their ids differ."""
        seen: dict[str, int] = {}
        chunks: list[ScoredChunk] = []
        for paper in papers:
            position = seen.get(paper.key, 0)
            seen[paper.key] = position + 1
            chunks.append(paper.to_chunk(ord_=position))
        return chunks

    async def _web(self, query: str) -> list[Paper]:
        assert self._kit.web is not None
        hits = await self._kit.web.discover(query)
        pages = await asyncio.gather(*(passages_for(self._kit.client, hit, query) for hit in hits))
        return [paper for page in pages for paper in page]

    @staticmethod
    async def _run_source(name: str, call: Awaitable[list[Paper]]) -> tuple[str, list[Paper], str | None]:
        """One failing source (down, rate limited, malformed) never fails the answer: it is reported and skipped."""
        try:
            return name, list(await call), None
        except EgressDenied as exc:
            return name, [], f"denied:{exc.reason}"
        except Exception as exc:  # a connector can fail in many ways (httpx, json, xml); none may fail the answer
            log.warning("public source %s failed: %s", name, type(exc).__name__)
            return name, [], type(exc).__name__
