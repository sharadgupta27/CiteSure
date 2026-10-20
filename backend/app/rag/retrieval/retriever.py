"""Composes the retrieval stages from a PipelineConfig, so experiments are configuration, not code forks."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.base import Embedder, Reranker
from app.observability import StageTimer
from app.rag.retrieval.fts import fts_search
from app.rag.retrieval.fusion import reciprocal_rank_fusion
from app.rag.retrieval.rerank import rerank
from app.rag.retrieval.vector import vector_search
from app.rag.types import PipelineConfig, RetrievalTrace


async def retrieve(
    session: AsyncSession,
    embedder: Embedder,
    reranker: Reranker | None,
    query: str,
    allowed_collection_ids: Sequence[uuid.UUID],
    config: PipelineConfig,
    timer: StageTimer | None = None,
) -> RetrievalTrace:
    timer = timer or StageTimer()
    trace = RetrievalTrace()

    with timer.stage("embed"):
        query_vector = await embedder.embed_query(query)
    with timer.stage("vector"):
        trace.vector = await vector_search(session, query_vector, allowed_collection_ids, config.candidate_k)

    if config.retrieval_mode == "hybrid":
        with timer.stage("fts"):
            trace.fts = await fts_search(session, query, allowed_collection_ids, config.candidate_k)
        with timer.stage("fuse"):
            trace.fused = reciprocal_rank_fusion([trace.vector, trace.fts], limit=config.candidate_k)
    else:
        trace.fused = list(trace.vector)

    if config.rerank and reranker is not None:
        with timer.stage("rerank"):
            trace.reranked = await rerank(reranker, query, trace.fused, config.top_k)
        trace.final = trace.reranked
    else:
        trace.final = trace.fused[: config.top_k]
    return trace
