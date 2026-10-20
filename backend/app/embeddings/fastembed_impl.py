"""Local ONNX embeddings and cross-encoder reranker via fastembed (the default for real deployments).

fastembed is imported lazily because it is an optional extra (`uv sync --extra ml`). Models are
downloaded once and cached; the production Docker image bakes them in so nothing is fetched at runtime.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any


class FastEmbedEmbedder:
    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        from fastembed import TextEmbedding

        self._model: Any = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.dim = len(next(iter(self._model.embed(["dimension probe"]))))
        self._query_cache: OrderedDict[str, list[float]] = OrderedDict()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        def run() -> list[list[float]]:
            return [[float(x) for x in v] for v in self._model.passage_embed(texts)]

        return await asyncio.to_thread(run)

    async def embed_query(self, text: str) -> list[float]:
        if text in self._query_cache:  # repeated questions are common; embedding is the slow part
            self._query_cache.move_to_end(text)
            return self._query_cache[text]

        def run() -> list[float]:
            return [float(x) for x in next(iter(self._model.query_embed([text])))]

        vector = await asyncio.to_thread(run)
        self._query_cache[text] = vector
        if len(self._query_cache) > 512:
            self._query_cache.popitem(last=False)
        return vector


class CrossEncoderReranker:
    def __init__(self, model_name: str = "Xenova/ms-marco-MiniLM-L-6-v2", cache_dir: str | None = None) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._model: Any = TextCrossEncoder(model_name=model_name, cache_dir=cache_dir)

    async def score(self, query: str, passages: list[str]) -> list[float]:
        def run() -> list[float]:
            return [float(s) for s in self._model.rerank(query, passages)]

        return await asyncio.to_thread(run)
