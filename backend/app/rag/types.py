"""Typed values passed between the RAG stages. Stages are pure units: typed in, typed out."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Literal


@dataclass(frozen=True)
class ScoredChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    collection_id: uuid.UUID
    ord: int
    text: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int
    score: float = 0.0

    def with_score(self, score: float) -> ScoredChunk:
        return replace(self, score=score)

    @property
    def context_text(self) -> str:
        """Text used for reranking: the heading gives a short passage the context it lost when chunked."""
        return " > ".join([*self.heading_path, ""]) + self.text if self.heading_path else self.text


@dataclass(frozen=True)
class PipelineConfig:
    retrieval_mode: Literal["vector", "hybrid"] = "hybrid"
    rerank: bool = True
    candidate_k: int = 30
    top_k: int = 6

    def as_dict(self) -> dict[str, object]:
        return {
            "retrieval_mode": self.retrieval_mode,
            "rerank": self.rerank,
            "candidate_k": self.candidate_k,
            "top_k": self.top_k,
        }


@dataclass
class RetrievalTrace:
    """Every stage's output, kept so /retrieval/explain and the evaluator can show where a chunk was lost."""

    vector: list[ScoredChunk] = field(default_factory=list)
    fts: list[ScoredChunk] = field(default_factory=list)
    fused: list[ScoredChunk] = field(default_factory=list)
    reranked: list[ScoredChunk] = field(default_factory=list)
    final: list[ScoredChunk] = field(default_factory=list)
