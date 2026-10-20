"""Keyword search with Postgres full-text search. Catches exact terms (policy ids, acronyms, numbers)
that embeddings blur. Also pre-filtered by the allowed collection ids."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document
from app.rag.retrieval.vector import to_scored
from app.rag.types import ScoredChunk

_TERM = re.compile(r"[A-Za-z0-9]+")


def build_tsquery(query: str) -> str | None:
    """OR together the alphanumeric terms. Only [A-Za-z0-9] survives, so the string is safe for to_tsquery,
    and OR (not AND) lets a long natural-language question still match on its informative words."""
    terms = list(dict.fromkeys(t.lower() for t in _TERM.findall(query)))
    return " | ".join(terms) if terms else None


async def fts_search(
    session: AsyncSession, query: str, allowed_collection_ids: Sequence[uuid.UUID], limit: int
) -> list[ScoredChunk]:
    tsquery_text = build_tsquery(query)
    if not allowed_collection_ids or tsquery_text is None:
        return []
    tsquery = func.to_tsquery(literal_column("'english'::regconfig"), tsquery_text)
    rank = func.ts_rank_cd(Chunk.tsv, tsquery)
    stmt = (
        select(Chunk, Document.title, rank.label("score"))
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.collection_id.in_(allowed_collection_ids), Document.status == "ready", Chunk.tsv.op("@@")(tsquery))
        .order_by(rank.desc(), Document.filename, Chunk.ord)  # stable tie-break: chunk ids are random per ingestion
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [to_scored(chunk, title, float(score)) for chunk, title, score in rows]
