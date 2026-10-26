"""Open-access full text of a published paper: find a legal PDF, fetch it through the egress client, turn it into
passages. Nothing here touches the database; `services/fulltext.py` stores the result.

What leaves the system is a paper identifier that is already public (a DOI, an arXiv id, a Europe PMC id, an OpenAlex
id), never question text or document text. The service still passes each identifier through the egress guard, because
a free-text field is a way to smuggle words out and the guard is the one place that decides what may leave.

Every download is bounded: https and allow-listed hosts only (the client), a byte cap, a total time limit, a PDF
magic number and content-type check, a page cap and a chunk cap checked before the expensive work.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import quote, unquote, urlparse

import pymupdf

from app.config import Settings
from app.egress import EgressClient, EgressDenied
from app.rag.chunking import chunk_sections
from app.rag.chunking.chunker import ChunkDraft
from app.rag.parsing import ParseError
from app.rag.parsing.pdf import parse_pdf
from app.rag.types import ScoredChunk
from app.research.connectors import (
    europepmc_oa_url,
    openalex_oa_urls,
    parse_arxiv,
    parse_openalex_work,
    parse_semantic_scholar_record,
)
from app.research.papers import EgressRecord, Paper

log = logging.getLogger("citesure.research.fulltext")

DESTINATION = "fulltext"  # the metrics label for every download (hosts vary; the label must not)
PDF_TYPES = frozenset({"application/pdf", "application/x-pdf", "application/octet-stream", "binary/octet-stream"})
_PYMUPDF: Any = pymupdf  # PyMuPDF ships no type information
MAX_ATTEMPTS = 4  # candidate PDF addresses tried for one paper

_DOI = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]{1,200}$")
_ARXIV = re.compile(r"^(?:\d{4}\.\d{4,5}|[a-z]+(?:-[a-z]+)*(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$")
_PMC_PATH = re.compile(r"^/(?:article|abstract)/([A-Z]{3,4})/([A-Za-z0-9]{1,20})/?$")
_OPENALEX = re.compile(r"^W\d{1,12}$")


class FullTextError(Exception):
    """A failure with a stable reason code. The service shows the user the message that belongs to the code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class FullTextIndex(Protocol):
    """What the public lane needs from the cache: passages of cached papers that match the question. Local only."""

    async def search(self, question: str, limit: int) -> list[ScoredChunk]: ...


# --- who is the paper? ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PaperRef:
    key: str  # doi:..., arxiv:..., europepmc:SRC/ID or openalex:W...
    url: str  # canonical landing page, what a citation links to
    identifier: str  # the public id that goes on the wire to the lookup APIs
    doi: str | None = None
    arxiv_id: str | None = None
    europepmc: tuple[str, str] | None = None
    openalex_id: str | None = None


def clean_doi(value: str) -> str | None:
    doi = unquote(value.strip()).lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        doi = doi.removeprefix(prefix)
    return doi if _DOI.match(doi) and ".." not in doi else None  # no path tricks in a lookup URL


def identify(url: str, doi: str | None = None) -> PaperRef:
    """Work out which paper a citation address or DOI names. Raises FullTextError('unsupported_source') otherwise.

    Only addresses that name a paper by a public identifier are accepted. An arbitrary web page is not: full text is
    for published papers, and the identifier is what is sent to the lookup APIs.
    """
    if doi:
        clean = clean_doi(doi)
        if clean is None:
            raise FullTextError("unsupported_source")
        return _doi_ref(clean)
    parts = urlparse(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = unquote(parts.path)
    if parts.scheme not in ("http", "https") or not host:
        raise FullTextError("unsupported_source")
    if host in ("doi.org", "dx.doi.org"):
        clean = clean_doi(parts.path.lstrip("/"))
        if clean:
            return _doi_ref(clean)
    elif host in ("arxiv.org", "export.arxiv.org"):
        match = re.match(r"^/(?:abs|pdf)/(.+?)(?:\.pdf)?$", path)
        if match and _ARXIV.match(match.group(1)):
            return _arxiv_ref(match.group(1))
    elif host == "europepmc.org":
        match = _PMC_PATH.match(path)
        if match:
            source, ident = match.groups()
            return PaperRef(
                key=f"europepmc:{source}/{ident}",
                url=f"https://europepmc.org/article/{source}/{ident}",
                identifier=f"{source}:{ident}",
                europepmc=(source, ident),
            )
    elif host == "openalex.org":
        ident = path.strip("/").upper()
        if _OPENALEX.match(ident):
            return PaperRef(
                key=f"openalex:{ident}", url=f"https://openalex.org/{ident}", identifier=ident, openalex_id=ident
            )
    raise FullTextError("unsupported_source")


def _doi_ref(doi: str) -> PaperRef:
    arxiv = doi.removeprefix("10.48550/arxiv.") if doi.startswith("10.48550/arxiv.") else None
    return PaperRef(
        key=f"doi:{doi}",
        url=f"https://doi.org/{doi}",
        identifier=doi,
        doi=doi,
        arxiv_id=arxiv if arxiv and _ARXIV.match(arxiv) else None,
    )


def _arxiv_ref(arxiv_id: str) -> PaperRef:
    base = re.sub(r"v\d+$", "", arxiv_id)
    return PaperRef(key=f"arxiv:{base}", url=f"https://arxiv.org/abs/{base}", identifier=f"arXiv:{base}", arxiv_id=base)


# --- where is a legal PDF? -----------------------------------------------------------------------------------------
@dataclass
class PaperMeta:
    title: str = ""
    authors: tuple[str, ...] = ()
    year: int | None = None
    doi: str | None = None

    def absorb(self, paper: Paper) -> None:
        """Keep the first non-empty value of each field, so the best-ranked source names the paper."""
        self.title = self.title or paper.title
        self.authors = self.authors or paper.authors
        self.year = self.year or paper.year
        self.doi = self.doi or (paper.doi or "").removeprefix("https://doi.org/").lower() or None


class Trail:
    """The egress records of one request: one entry per destination, truthful about what was sent and what failed."""

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        self.records: list[EgressRecord] = []

    def add(self, destination: str, status: Literal["sent", "blocked", "failed"], reason: str | None = None) -> None:
        # A blocked step never left, so it carries no text. A failed one may have (a timeout after sending).
        record = EgressRecord(
            destination=destination, status=status, query=None if status == "blocked" else self.identifier, reason=reason
        )
        if record not in self.records:
            self.records.append(record)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "unknown").lower()


Lookup = Callable[[], Awaitable[list[str]]]


class OpenAccessFinder:
    """Asks the enabled scholarly APIs, one after another, where an open-access PDF of the paper lives. Each
    answer yields candidate addresses; the caller tries them in order and stops at the first real PDF."""

    def __init__(self, client: EgressClient, settings: Settings, trail: Trail) -> None:
        self._client = client
        self._sources = set(settings.public_source_list)
        self._mailto = settings.contact_email
        self._trail = trail
        self.meta = PaperMeta()

    async def _get(self, url: str, params: dict[str, str]) -> bytes | None:
        host = _host(url)
        try:
            response = await self._client.get(DESTINATION, url, params=params, fingerprint_of=self._trail.identifier)
        except EgressDenied as exc:
            self._trail.add(host, "blocked", exc.reason)
            return None
        except Exception as exc:  # httpx has its own error tree; one failing lookup moves on to the next source
            self._trail.add(host, "failed", type(exc).__name__)
            return None
        if response.status != 200:
            self._trail.add(host, "failed", f"http_{response.status}")
            return None
        self._trail.add(host, "sent")
        return response.content

    async def _json(self, url: str, params: dict[str, str]) -> Any | None:
        content = await self._get(url, params)
        if content is None:
            return None
        try:
            return json.loads(content)
        except ValueError:
            self._trail.add(_host(url), "failed", "bad_response")
            return None

    async def candidates(self, ref: PaperRef) -> AsyncIterator[str]:
        """Candidate PDF addresses, best first. A later lookup only runs when the earlier ones are exhausted."""
        seen: set[str] = set()
        for lookup in self._lookups(ref):
            for url in await lookup():
                if url not in seen:
                    seen.add(url)
                    yield url

    def _lookups(self, ref: PaperRef) -> list[Lookup]:
        steps: list[Lookup] = []
        if ref.arxiv_id:
            arxiv_id = ref.arxiv_id
            steps.append(lambda: self._arxiv(arxiv_id))
        if ref.openalex_id and "openalex" in self._sources:
            openalex_url = f"https://api.openalex.org/works/{ref.openalex_id}"
            steps.append(lambda: self._openalex(openalex_url))
        if ref.doi and "openalex" in self._sources:
            doi_url = f"https://api.openalex.org/works/doi:{quote(ref.doi, safe='/')}"
            steps.append(lambda: self._openalex(doi_url))
        if ref.doi and "semanticscholar" in self._sources:
            s2_id = f"DOI:{quote(ref.doi, safe='/')}"
            steps.append(lambda: self._semantic_scholar(s2_id))
        if "europepmc" in self._sources:
            if ref.doi:
                query = f'DOI:"{ref.doi}"'
            elif ref.europepmc:
                query = f"EXT_ID:{ref.europepmc[1]} AND SRC:{ref.europepmc[0]}"
            else:
                return steps
            steps.append(lambda: self._europepmc(query))
        return steps

    async def _arxiv(self, arxiv_id: str) -> list[str]:
        content = await self._get("https://export.arxiv.org/api/query", {"id_list": arxiv_id, "max_results": "1"})
        if content is not None:
            try:
                for paper in parse_arxiv(content):
                    self.meta.absorb(paper)
            except (ValueError, ET.ParseError):
                self._trail.add("export.arxiv.org", "failed", "bad_response")
        return [f"https://arxiv.org/pdf/{arxiv_id}"]  # arXiv always has the PDF; the title lookup is a bonus

    async def _openalex(self, url: str) -> list[str]:
        params = {
            "select": "id,doi,display_name,publication_year,authorships,primary_location,"
            "best_oa_location,open_access,locations"
        }
        if self._mailto:
            params["mailto"] = self._mailto
        work = await self._json(url, params)
        if not isinstance(work, dict):
            return []
        self.meta.absorb(parse_openalex_work(work))
        return openalex_oa_urls(work)

    async def _semantic_scholar(self, paper_id: str) -> list[str]:
        record = await self._json(
            f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}",
            {"fields": "title,year,authors,url,externalIds,openAccessPdf"},
        )
        if not isinstance(record, dict):
            return []
        paper = parse_semantic_scholar_record(record)
        self.meta.absorb(paper)
        return [paper.oa_url] if paper.oa_url else []

    async def _europepmc(self, query: str) -> list[str]:
        data = await self._json(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            {"query": query, "format": "json", "resultType": "core", "pageSize": "1"},
        )
        results = data.get("resultList", {}).get("result", []) if isinstance(data, dict) else []
        if not results:
            return []
        record = results[0]
        self.meta.absorb(
            Paper(
                source="europepmc",
                title=str(record.get("title", "")).strip(),
                text="",
                url="",
                year=_int(record.get("pubYear")),
                doi=record.get("doi"),
            )
        )
        url = europepmc_oa_url(record)
        return [url] if url else []


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --- fetching ------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class FetchedPdf:
    data: bytes
    sha256: str
    host: str
    url: str


_DENIED_CODES = {"response_too_large": "too_large", "not_allowed": "host_not_allowed"}


async def fetch_pdf(client: EgressClient, settings: Settings, url: str, trail: Trail) -> FetchedPdf:
    """Download one candidate address. Raises FullTextError with a code on every refusal; records the attempt."""
    host = _host(url)
    try:
        async with asyncio.timeout(settings.fulltext_timeout_s):
            response = await client.get(
                DESTINATION,
                url,
                fingerprint_of=trail.identifier,
                max_bytes=settings.fulltext_max_bytes,
                accept="application/pdf",
            )
    except EgressDenied as exc:
        trail.add(host, "blocked", exc.reason)
        raise FullTextError(_DENIED_CODES.get(exc.reason, "blocked")) from exc
    except TimeoutError as exc:
        trail.add(host, "failed", "timeout")
        raise FullTextError("timeout") from exc
    except Exception as exc:
        trail.add(host, "failed", type(exc).__name__)
        raise FullTextError("fetch_failed") from exc
    if response.status != 200:
        trail.add(host, "failed", f"http_{response.status}")
        raise FullTextError("fetch_failed")
    if response.content_type not in PDF_TYPES or not response.content.startswith(b"%PDF-"):
        trail.add(host, "failed", "not_pdf")  # a landing page or a paywall notice, not the paper
        raise FullTextError("not_pdf")
    trail.add(host, "sent")
    return FetchedPdf(response.content, hashlib.sha256(response.content).hexdigest(), host, response.url)


async def find_and_fetch(
    client: EgressClient, settings: Settings, finder: OpenAccessFinder, ref: PaperRef, trail: Trail
) -> FetchedPdf:
    """Try the candidate addresses in order. The error reports the most useful reason when none worked."""
    failures: list[str] = []
    attempts = 0
    async for url in finder.candidates(ref):
        if attempts >= MAX_ATTEMPTS:
            break
        attempts += 1
        try:
            return await fetch_pdf(client, settings, url, trail)
        except FullTextError as exc:
            failures.append(exc.code)
    if not failures:
        raise FullTextError("no_open_access")
    for code in ("too_large", "host_not_allowed", "timeout"):  # actionable reasons first
        if code in failures:
            raise FullTextError(code)
    raise FullTextError("no_open_access" if set(failures) <= {"not_pdf", "fetch_failed"} else failures[0])


# --- turning the PDF into passages ---------------------------------------------------------------------------------
@dataclass
class Passages:
    title: str
    page_count: int
    drafts: list[ChunkDraft] = field(default_factory=list)


def _page_count(data: bytes) -> int:
    try:
        doc = _PYMUPDF.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise FullTextError("unreadable") from exc
    try:
        return int(doc.page_count)
    finally:
        doc.close()


async def build_passages(data: bytes, settings: Settings, fallback_title: str) -> Passages:
    """Parse and chunk with the same code as company documents, after the cheap size checks.

    The page count is read first and a long PDF is refused before any text extraction. The parse runs in a thread
    with a time limit, so a pathological file cannot hold the worker; it cannot be killed mid-parse, which is why the
    byte and page caps come first."""
    pages = _page_count(data)
    if pages > settings.fulltext_max_pages:
        raise FullTextError("too_long")
    try:
        parsed = await asyncio.wait_for(asyncio.to_thread(parse_pdf, data, "paper.pdf"), settings.fulltext_parse_timeout_s)
    except TimeoutError as exc:
        raise FullTextError("timeout") from exc
    except ParseError as exc:
        log.info("full text not parsed: %s", type(exc).__name__)
        raise FullTextError("unreadable") from exc
    _, drafts = chunk_sections(parsed.sections, target_tokens=settings.chunk_tokens, overlap=settings.chunk_overlap)
    if not drafts:
        raise FullTextError("unreadable")
    if len(drafts) > settings.fulltext_max_chunks:
        raise FullTextError("too_long")
    return Passages(title=fallback_title or parsed.title, page_count=pages, drafts=drafts)
