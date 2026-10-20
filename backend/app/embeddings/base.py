from __future__ import annotations

from typing import Protocol


class Embedder(Protocol):
    dim: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    """Scores (query, passage) pairs; higher is more relevant."""

    async def score(self, query: str, passages: list[str]) -> list[float]: ...
