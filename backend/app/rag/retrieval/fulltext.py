"""Search over the public full-text cache (papers a user added with "Fetch full text").

This is a different table from `chunks` on purpose. The internal searches filter by the asker's collections; a
published paper belongs to no collection, so there is nothing to filter by and nothing here can return company text.
Only the public lane calls this module, and only for scope `public` or `both`. Expired papers are ignored.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.base import Embedder
from app.models.fulltext import FullTextChunk, FullTextPaper
from app.rag.retrieval.fts import build_tsquery
from app.rag.retrieval.fusion import reciprocal_rank_fusion
from app.rag.retrieval.vector import _enable_iterative_scan
from app.rag.types import ScoredChunk
from app.research.papers import PUBLIC_COLLECTION_ID

_FRESH = FullTextPaper.expires_at > func.now()


def chunk_id_for(paper_id: uuid.UUID, ord_: int) -> uuid.UUID:
    """Stable across a refetch of the same paper, so a stored answer's chunk id still names the same passage."""
    return uuid.uuid5(paper_id, str(ord_))


def to_public_chunk(chunk: FullTextChunk, paper: FullTextPaper, score: float) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk.id,
        document_id=paper.id,
        document_title=paper.label,
        collection_id=PUBLIC_COLLECTION_ID,
        ord=chunk.ord,
        text=chunk.text,
        heading_path=list(chunk.heading_path or []),
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        score=score,
        source_type="public",
        url=paper.url,
    )


async def vector_search(session: AsyncSession, embedding: list[float], limit: int) -> list[ScoredChunk]:
    await _enable_iterative_scan(session)
    distance = FullTextChunk.embedding.cosine_distance(embedding)
    stmt = (
        select(FullTextChunk, FullTextPaper, (1 - distance).label("score"))
        .join(FullTextPaper, FullTextPaper.id == FullTextChunk.paper_id)
        .where(_FRESH)
        .order_by(distance, FullTextPaper.label, FullTextChunk.ord)
        .limit(limit)
    )
    return [to_public_chunk(c, p, float(score)) for c, p, score in (await session.execute(stmt)).all()]


async def fts_search(session: AsyncSession, query: str, limit: int) -> list[ScoredChunk]:
    tsquery_text = build_tsquery(query)
    if tsquery_text is None:
        return []
    tsquery = func.to_tsquery(literal_column("'english'::regconfig"), tsquery_text)
    rank = func.ts_rank_cd(FullTextChunk.tsv, tsquery)
    stmt = (
        select(FullTextChunk, FullTextPaper, rank.label("score"))
        .join(FullTextPaper, FullTextPaper.id == FullTextChunk.paper_id)
        .where(_FRESH, FullTextChunk.tsv.op("@@")(tsquery))
        .order_by(rank.desc(), FullTextPaper.label, FullTextChunk.ord)
        .limit(limit)
    )
    return [to_public_chunk(c, p, float(score)) for c, p, score in (await session.execute(stmt)).all()]


class FullTextRetriever:
    """The public lane's view of the cache (research.fulltext.FullTextIndex). The question is only compared with
    text already stored here; nothing leaves the process."""

    def __init__(self, session: AsyncSession, embedder: Embedder, candidate_k: int = 30) -> None:
        self._session = session
        self._embedder = embedder
        self._candidate_k = candidate_k

    async def search(self, question: str, limit: int) -> list[ScoredChunk]:
        """Passages that share a content word with the question, ordered by keyword and vector rank together.

        The keyword match is a gate: a nearest-neighbour search always returns something, and unrelated passages from
        some other cached paper would otherwise take slots from relevant abstracts.
        """
        # A savepoint, so a database error here cannot poison the transaction the answer is stored in.
        async with self._session.begin_nested():
            keyword = await fts_search(self._session, question, self._candidate_k)
            if not keyword:  # nothing cached, or nothing relevant: skip the embedding
                return []
            vector = await vector_search(self._session, await self._embedder.embed_query(question), self._candidate_k)
        matched = {c.chunk_id for c in keyword}
        return reciprocal_rank_fusion([[c for c in vector if c.chunk_id in matched], keyword], limit=limit)
