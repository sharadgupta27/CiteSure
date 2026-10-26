"""Open-access full text on demand: request, budget, background fetch, cache (docs/open-access-fulltext.md).

A request is cheap and runs in the request handler (identify the paper, check the budget, enqueue). The download, the
parse and the embedding run in the worker, like ingestion. Public full text goes to its own tables and is only read
by the public lane; it never becomes a document, a chunk of the internal corpus, or part of anyone's ACL space.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from prometheus_client import Counter
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.egress import EgressGuard
from app.egress.corpus import SqlInternalCorpus
from app.errors import InvalidInput, NotFound, TooManyRequests
from app.models.fulltext import FullTextPaper, FullTextRequest
from app.providers import Providers
from app.repositories import fulltext as repo
from app.repositories import jobs as jobs_repo
from app.research.fulltext import (
    FullTextError,
    OpenAccessFinder,
    PaperRef,
    Trail,
    build_passages,
    find_and_fetch,
    identify,
)
from app.research.papers import EgressRecord, Paper
from app.research.service import public_reasons
from app.schemas import api as api_schemas
from app.schemas import fulltext as s
from app.services import acl
from app.services.ingest import EMBED_BATCH, embedding_input, fts_input

FULLTEXT_JOB = "fulltext_fetch"
log = logging.getLogger("citesure.fulltext")

FULLTEXT_REQUESTS = Counter("citesure_fulltext_requests_total", "Open-access full text requests by outcome", ["outcome"])

# What the user is told for each reason code. None of these quotes a URL, an identifier or any text.
MESSAGES: dict[str, str] = {
    "disabled": "Open-access full text is not turned on for this server.",
    "unsupported_source": (
        "This address does not name a paper CiteSure can look up. Open the paper from a DOI, arXiv, Europe PMC "
        "or OpenAlex link."
    ),
    "blocked": "The request was held back by the egress check, so nothing was sent.",
    "no_open_access": "No open-access PDF was found for this paper. The abstract stays available.",
    "host_not_allowed": "An open-access copy exists, but it is hosted somewhere this server is not allowed to reach.",
    "fetch_failed": "The open-access copy could not be downloaded. Try again later.",
    "not_pdf": "The address that was found is not a PDF (often a publisher page).",
    "too_large": "The PDF is larger than this server's limit for a single paper.",
    "too_long": "The paper is longer than this server's limit, so it was not added.",
    "unreadable": "The PDF could not be read as text (it may be scanned, encrypted or damaged).",
    "timeout": "The download took too long and was stopped.",
    "internal_error": "Something went wrong while adding the paper. Try again later.",
}
BUDGET_MESSAGE = (
    "This workspace has used its {limit} open-access downloads for today. Papers already added stay available; "
    "try again tomorrow, or ask an administrator to raise FULLTEXT_DAILY_FETCHES."
)


class FullTextBudgetExceeded(TooManyRequests):
    code = "fulltext_budget_exceeded"


def paper_id_for(paper_key: str) -> uuid.UUID:
    """The same id the paper's abstract passages use as their document id (research/papers.py)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, paper_key)


def day_start() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _egress_json(records: list[EgressRecord]) -> list[dict[str, Any]]:
    return [{"destination": r.destination, "status": r.status, "query": r.query, "reason": r.reason} for r in records]


class FullTextService:
    def __init__(self, session: AsyncSession, settings: Settings, providers: Providers) -> None:
        self.session = session
        self.settings = settings
        self.providers = providers

    async def _remaining(self, workspace_id: uuid.UUID) -> int:
        used = await repo.downloads_today(self.session, workspace_id, day_start())
        return max(0, self.settings.fulltext_daily_fetches - used)

    async def _status(self, row: FullTextRequest) -> s.FullTextStatus:
        return s.FullTextStatus(
            id=row.id,
            status=row.status,
            title=row.title,
            passages=row.chunk_count,
            pages=row.page_count,
            cached=row.cached,
            error=row.error,
            message=MESSAGES.get(row.error or "") if row.error else None,
            fetches_remaining=await self._remaining(row.workspace_id),
            egress=[api_schemas.EgressRecord(**record) for record in row.egress or []],
        )

    async def request(self, user_id: uuid.UUID, body: s.FullTextFetchRequest) -> s.FullTextStatus:
        if not self.settings.fulltext_on or self.providers.research is None:
            raise InvalidInput(MESSAGES["disabled"])
        await acl.context_for_workspace(self.session, user_id, body.workspace_id)  # 404 for a non-member
        try:
            ref = identify(body.url, body.doi)
        except FullTextError as exc:
            raise InvalidInput(MESSAGES[exc.code]) from exc

        await repo.lock_workspace_budget(self.session, body.workspace_id)
        shared = await repo.in_flight(self.session, body.workspace_id, ref.key)
        if shared is not None:  # a second click while the first is running costs nothing and tracks the same job
            return await self._status(shared)

        common: dict[str, Any] = {
            "workspace_id": body.workspace_id,
            "user_id": user_id,
            "paper_key": ref.key,
            "url": ref.url,
            "doi": ref.doi,
        }
        cached = await repo.fresh_paper(self.session, ref.key)
        if cached is not None:  # already in the cache: nothing is downloaded, so nothing is charged
            row = await repo.create_request(
                self.session,
                **common,
                status="ready",
                cached=True,
                counted=False,
                paper_id=cached.id,
                title=cached.label,
                chunk_count=cached.chunk_count,
                page_count=cached.page_count,
                egress=[],
                finished_at=datetime.now(UTC),
            )
            await self.session.commit()
            FULLTEXT_REQUESTS.labels(outcome="cached").inc()
            return await self._status(row)

        if await self._remaining(body.workspace_id) <= 0:
            FULLTEXT_REQUESTS.labels(outcome="over_budget").inc()
            raise FullTextBudgetExceeded(BUDGET_MESSAGE.format(limit=self.settings.fulltext_daily_fetches))
        row = await repo.create_request(self.session, **common, status="queued", counted=True, egress=[])
        await jobs_repo.enqueue(self.session, FULLTEXT_JOB, {"request_id": str(row.id)}, max_attempts=1)
        await self.session.commit()
        return await self._status(row)

    async def status(self, user_id: uuid.UUID, request_id: uuid.UUID) -> s.FullTextStatus:
        row = await repo.get_request(self.session, request_id)
        if row is None or row.user_id != user_id:  # one user's requests are not another's business
            raise NotFound("Request not found")
        return await self._status(row)


# --- the worker side -----------------------------------------------------------------------------------------------
# DOIs often contain digit runs that look like phone numbers (10.1038/s41586-020-2649-2). That reason alone does not
# stop a lookup; every other reason (secrets, e-mail, deny terms, canaries, text copied from a document) does.
_IGNORED_REASONS = frozenset({"pii:phone"})


async def _check_identifier(session: AsyncSession, settings: Settings, ref: PaperRef, trail: Trail) -> None:
    decision = await EgressGuard(settings, SqlInternalCorpus(session)).check(ref.identifier, kind="query")
    blocking = tuple(r for r in decision.reasons if r not in _IGNORED_REASONS)
    if blocking:
        trail.add("public", "blocked", ",".join(public_reasons(blocking)))  # reason codes, never the text
        raise FullTextError("blocked")


async def run_fulltext_job(session: AsyncSession, providers: Providers, settings: Settings, request_id: uuid.UUID) -> None:
    """Fetch, parse, embed and store one paper. Every outcome is written to the request row; nothing is retried,
    because a retry would download again (and a deterministic failure fails again)."""
    row = await repo.get_request(session, request_id)
    if row is None or row.status in ("ready", "failed"):
        return
    await repo.update_request(session, request_id, status="running")
    await session.commit()

    trail = Trail("")
    try:
        ref = identify(row.url, row.doi)
        trail = Trail(ref.identifier)
        paper = await _execute(session, providers, settings, ref, trail)
    except FullTextError as exc:
        await _finish(session, request_id, trail, error=exc.code)
        return
    except Exception as exc:  # database, embedding or parser trouble: report a code, never the exception text
        log.warning("full text request failed: %s", type(exc).__name__)
        await session.rollback()
        await _finish(session, request_id, trail, error="internal_error")
        return
    await _finish(session, request_id, trail, paper=paper)


async def _finish(
    session: AsyncSession,
    request_id: uuid.UUID,
    trail: Trail,
    *,
    paper: FullTextPaper | None = None,
    error: str | None = None,
) -> None:
    # Charged only when something actually left: a cache hit or a request the guard stopped costs nothing.
    left = any(r.status != "blocked" for r in trail.records)
    values: dict[str, Any] = {
        "status": "ready" if paper is not None else "failed",
        "error": error,
        "counted": left,
        "cached": paper is not None and not left,
        "egress": _egress_json(trail.records),
        "finished_at": datetime.now(UTC),
    }
    if paper is not None:
        values.update(paper_id=paper.id, title=paper.label, chunk_count=paper.chunk_count, page_count=paper.page_count)
    await repo.update_request(session, request_id, **values)
    await session.commit()
    FULLTEXT_REQUESTS.labels(outcome="ready" if paper is not None else (error or "failed")).inc()


async def _execute(
    session: AsyncSession, providers: Providers, settings: Settings, ref: PaperRef, trail: Trail
) -> FullTextPaper:
    if providers.research is None or not settings.fulltext_on:
        raise FullTextError("disabled")
    existing = await repo.fresh_paper(session, ref.key)
    if existing is not None:  # another request finished first
        return existing

    await _check_identifier(session, settings, ref, trail)
    client = providers.research.client
    finder = OpenAccessFinder(client, settings, trail)
    pdf = await find_and_fetch(client, settings, finder, ref, trail)
    passages = await build_passages(pdf.data, settings, finder.meta.title)

    title = (passages.title or ref.key)[:500]
    label = Paper(
        source="fulltext", title=title, text="", url=ref.url, authors=finder.meta.authors, year=finder.meta.year
    ).label
    inputs = [embedding_input(title, d.heading_path, d.text) for d in passages.drafts]
    vectors: list[list[float]] = []
    for start in range(0, len(inputs), EMBED_BATCH):
        vectors += await providers.embedder.embed_documents(inputs[start : start + EMBED_BATCH])
    rows = [
        {
            "ord": d.ord,
            "text": d.text,
            "heading_path": d.heading_path,
            "page_start": d.page_start,
            "page_end": d.page_end,
            "char_start": d.char_start,
            "char_end": d.char_end,
            "token_count": d.token_count,
            "embedding": vector,
            "fts_text": fts_input(title, d.heading_path, d.text),
        }
        for d, vector in zip(passages.drafts, vectors, strict=True)
    ]
    return await repo.replace_paper(
        session,
        {
            "id": paper_id_for(ref.key),
            "paper_key": ref.key,
            "doi": ref.doi or finder.meta.doi,
            "url": ref.url,
            "title": title,
            "label": label[:600],
            "year": finder.meta.year,
            "source_host": pdf.host[:255],
            "sha256": pdf.sha256,
            "size_bytes": len(pdf.data),
            "page_count": passages.page_count,
            "chunk_count": len(rows),
        },
        rows,
        ttl_days=settings.fulltext_cache_ttl_days,
    )
