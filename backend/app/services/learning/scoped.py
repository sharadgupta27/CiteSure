"""Retrieval narrowed to one chosen document: the same hybrid search, fusion and rerank stages as /ask, with the
ACL filter in the SQL (repositories/learning_sources.py)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.providers import Providers
from app.rag.retrieval.fusion import reciprocal_rank_fusion
from app.rag.retrieval.rerank import rerank
from app.rag.types import ScoredChunk
from app.repositories import learning_sources as sources_repo


async def top_chunks_in_document(
    session: AsyncSession,
    providers: Providers,
    settings: Settings,
    *,
    query: str,
    query_vector: list[float],
    document_id: uuid.UUID,
    allowed_collection_ids: Sequence[uuid.UUID],
    limit: int,
) -> list[ScoredChunk]:
    vector = await sources_repo.vector_in_document(
        session, query_vector, document_id, allowed_collection_ids=allowed_collection_ids, limit=settings.candidate_k
    )
    keyword = await sources_repo.fts_in_document(
        session, query, document_id, allowed_collection_ids=allowed_collection_ids, limit=settings.candidate_k
    )
    fused = reciprocal_rank_fusion([vector, keyword], limit=settings.candidate_k)
    if settings.rerank_enabled and providers.reranker is not None:
        return await rerank(providers.reranker, query, fused, limit)
    return fused[:limit]
