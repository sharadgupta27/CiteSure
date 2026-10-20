"""Reciprocal Rank Fusion: merge ranked lists using ranks only, so vector scores (0..1 similarity) and
full-text scores (unbounded) never have to be normalised against each other."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.rag.types import ScoredChunk

RRF_K = 60  # the constant from the original paper; larger values flatten the advantage of the top ranks


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[ScoredChunk]], *, k: int = RRF_K, limit: int | None = None
) -> list[ScoredChunk]:
    scores: dict[uuid.UUID, float] = {}
    first_seen: dict[uuid.UUID, ScoredChunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(chunk.chunk_id, chunk)
    # Ties are broken by (document, position), not by chunk id: ids are random per ingestion, which made evaluation
    # metrics change between identical runs.
    ordered = sorted(scores, key=lambda cid: (-scores[cid], first_seen[cid].document_title, first_seen[cid].ord, str(cid)))
    fused = [first_seen[cid].with_score(scores[cid]) for cid in ordered]
    return fused[:limit] if limit is not None else fused
