"""Chunk and document lookups for the summarize, compare and plan agents.

Same rule as retrieval: every statement filters by `allowed_collection_ids` in SQL (non-negotiable 1). The searches
here are the retrieval SQL narrowed to chosen documents, so the agents read the same index, with the same ACL, as /ask."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, literal_column, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document
from app.rag.retrieval.fts import build_tsquery
from app.rag.retrieval.vector import to_scored
from app.rag.types import ScoredChunk

AllowedIds = Sequence[uuid.UUID]


@dataclass(frozen=True)
class ChunkMeta:
    """A chunk without its text: enough to lay out a reading plan without loading the document."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    ord: int
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    token_count: int


async def readable_documents(
    session: AsyncSession, document_ids: Sequence[uuid.UUID], *, allowed_collection_ids: AllowedIds
) -> list[Document]:
    if not document_ids:
        return []
    stmt = select(Document).where(Document.id.in_(document_ids), Document.collection_id.in_(allowed_collection_ids))
    return list((await session.execute(stmt)).scalars().all())


async def chunk_meta(
    session: AsyncSession, document_ids: Sequence[uuid.UUID], *, allowed_collection_ids: AllowedIds
) -> dict[uuid.UUID, list[ChunkMeta]]:
    if not document_ids:
        return {}
    stmt = (
        select(
            Chunk.id, Chunk.document_id, Chunk.ord, Chunk.heading_path, Chunk.page_start, Chunk.page_end, Chunk.token_count
        )
        .where(Chunk.document_id.in_(document_ids), Chunk.collection_id.in_(allowed_collection_ids))
        .order_by(Chunk.document_id, Chunk.ord)
    )
    out: dict[uuid.UUID, list[ChunkMeta]] = {}
    for cid, did, ord_, heading, p0, p1, tokens in (await session.execute(stmt)).all():
        out.setdefault(did, []).append(ChunkMeta(cid, did, ord_, list(heading or []), p0, p1, tokens))
    return out


async def chunks_by_ids(
    session: AsyncSession, chunk_ids: Sequence[uuid.UUID], *, allowed_collection_ids: AllowedIds
) -> list[ScoredChunk]:
    """The chunks with their text, in reading order (document title, then position)."""
    if not chunk_ids:
        return []
    stmt = (
        select(Chunk, Document.title)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id.in_(chunk_ids), Chunk.collection_id.in_(allowed_collection_ids), Document.status == "ready")
        .order_by(Document.filename, Chunk.ord)
    )
    return [to_scored(chunk, title, 0.0) for chunk, title in (await session.execute(stmt)).all()]


async def _enable_iterative_scan(session: AsyncSession) -> None:
    """A document filter is far more selective than the ACL filter: let the HNSW scan keep walking until it has
    enough rows from this document (pgvector >= 0.8; older versions ignore the setting)."""
    try:
        async with session.begin_nested():
            await session.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))
            await session.execute(text("SET LOCAL hnsw.ef_search = 200"))
    except DBAPIError:
        pass


async def vector_in_document(
    session: AsyncSession, embedding: list[float], document_id: uuid.UUID, *, allowed_collection_ids: AllowedIds, limit: int
) -> list[ScoredChunk]:
    if not allowed_collection_ids:
        return []
    await _enable_iterative_scan(session)
    distance = Chunk.embedding.cosine_distance(embedding)
    stmt = (
        select(Chunk, Document.title, (1 - distance).label("score"))
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.document_id == document_id,
            Chunk.collection_id.in_(allowed_collection_ids),
            Document.status == "ready",
        )
        .order_by(distance, Chunk.ord)
        .limit(limit)
    )
    return [to_scored(c, title, float(score)) for c, title, score in (await session.execute(stmt)).all()]


async def fts_in_document(
    session: AsyncSession, query: str, document_id: uuid.UUID, *, allowed_collection_ids: AllowedIds, limit: int
) -> list[ScoredChunk]:
    tsquery_text = build_tsquery(query)
    if not allowed_collection_ids or tsquery_text is None:
        return []
    tsquery = func.to_tsquery(literal_column("'english'::regconfig"), tsquery_text)
    rank = func.ts_rank_cd(Chunk.tsv, tsquery)
    stmt = (
        select(Chunk, Document.title, rank.label("score"))
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.document_id == document_id,
            Chunk.collection_id.in_(allowed_collection_ids),
            Document.status == "ready",
            Chunk.tsv.op("@@")(tsquery),
        )
        .order_by(rank.desc(), Chunk.ord)
        .limit(limit)
    )
    return [to_scored(c, title, float(score)) for c, title, score in (await session.execute(stmt)).all()]
