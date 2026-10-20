"""Vector search. The ACL filter is part of the same SQL statement as the similarity search."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document
from app.rag.types import ScoredChunk


async def _enable_iterative_scan(session: AsyncSession) -> None:
    """With a WHERE filter, a plain HNSW scan can return fewer rows than asked for. Iterative scans keep
    walking the index until enough rows pass the ACL filter (pgvector >= 0.8). Older versions ignore this."""
    try:
        async with session.begin_nested():
            await session.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))
            await session.execute(text("SET LOCAL hnsw.ef_search = 100"))
    except DBAPIError:
        pass


def to_scored(chunk: Chunk, title: str, score: float) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        document_title=title,
        collection_id=chunk.collection_id,
        ord=chunk.ord,
        text=chunk.text,
        heading_path=list(chunk.heading_path or []),
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        score=score,
    )


async def vector_search(
    session: AsyncSession, embedding: list[float], allowed_collection_ids: Sequence[uuid.UUID], limit: int
) -> list[ScoredChunk]:
    if not allowed_collection_ids:
        return []
    await _enable_iterative_scan(session)
    distance = Chunk.embedding.cosine_distance(embedding)
    stmt = (
        select(Chunk, Document.title, (1 - distance).label("score"))
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.collection_id.in_(allowed_collection_ids), Document.status == "ready")
        .order_by(distance, Document.filename, Chunk.ord)  # stable tie-break: chunk ids are random per ingestion
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [to_scored(chunk, title, float(score)) for chunk, title, score in rows]
