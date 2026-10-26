"""Values of the public lane. A `Paper` is anything published that we can quote: a paper abstract or a web page passage."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Literal

from app.rag.types import ScoredChunk

# Public passages have no database row. Their ids are derived from the address, so the same paper found by two
# sources gets one id and rank fusion merges the two hits.
PUBLIC_COLLECTION_ID = uuid.UUID("00000000-0000-0000-0000-00000000babe")
MAX_PASSAGE_CHARS = 4000
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Paper:
    source: str  # arxiv | crossref | openalex | europepmc | semanticscholar | web
    title: str
    text: str  # the abstract or passage that can be quoted
    url: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    doi: str | None = None
    # Where an open-access copy may be read, as reported by the source (OpenAlex, arXiv, Europe PMC, Semantic Scholar).
    # It is a hint, never fetched on its own: `research/fulltext.py` validates and fetches it through the egress client.
    oa_url: str | None = None

    @property
    def key(self) -> str:
        """Identity across sources: the DOI when there is one, else the normalised title (a web page: its address)."""
        if self.source == "web":
            return "url:" + self.url
        if self.doi:
            return "doi:" + self.doi.lower().removeprefix("https://doi.org/")
        return "title:" + re.sub(r"[^a-z0-9]+", " ", self.title.lower()).strip()

    @property
    def label(self) -> str:
        who = ""
        if self.authors:
            who = self.authors[0].split(",")[0].split(" ")[-1] + (" et al." if len(self.authors) > 1 else "")
        suffix = ", ".join(part for part in (who, str(self.year) if self.year else "") if part)
        return f"{self.title} ({suffix})" if suffix else self.title

    def to_chunk(self, ord_: int = 0, text: str | None = None) -> ScoredChunk:
        body = _WS.sub(" ", text if text is not None else self.text).strip()[:MAX_PASSAGE_CHARS]
        seed = self.key if ord_ == 0 else f"{self.key}#{ord_}"
        chunk_id = uuid.uuid5(uuid.NAMESPACE_URL, seed)
        return ScoredChunk(
            chunk_id=chunk_id,
            document_id=uuid.uuid5(uuid.NAMESPACE_URL, self.key),
            document_title=self.label,
            collection_id=PUBLIC_COLLECTION_ID,
            ord=ord_,
            text=body,
            heading_path=[self.title],
            page_start=None,
            page_end=None,
            char_start=0,
            char_end=len(body),
            source_type="public",
            url=self.url,
        )


@dataclass(frozen=True)
class EgressRecord:
    """What the answer reports about the public lane: where a query was sent, or why nothing was."""

    destination: str
    status: Literal["sent", "blocked", "failed"]
    query: str | None = None  # present only when the text actually left
    reason: str | None = None


@dataclass
class ResearchResult:
    chunks: list[ScoredChunk] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    records: list[EgressRecord] = field(default_factory=list)
    question_cleared: bool = False  # the full question passed the guard, so a hosted model may read it
    query: str | None = None
