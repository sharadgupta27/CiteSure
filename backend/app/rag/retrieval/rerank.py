from __future__ import annotations

from app.embeddings.base import Reranker
from app.rag.types import ScoredChunk


async def rerank(reranker: Reranker, query: str, candidates: list[ScoredChunk], top_k: int) -> list[ScoredChunk]:
    """Re-score candidates by reading query and passage together, then keep the best top_k.
    The sort is stable on the incoming (fused) order so equal scores keep their earlier rank."""
    if not candidates:
        return []
    scores = await reranker.score(query, [c.context_text for c in candidates])
    order = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
    return [candidates[i].with_score(scores[i]) for i in order[:top_k]]
