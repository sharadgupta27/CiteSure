from __future__ import annotations

from app.config import Settings
from app.embeddings.base import Embedder, Reranker
from app.embeddings.fake import FakeEmbedder, LexicalReranker


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "fastembed":
        from app.embeddings.fastembed_impl import FastEmbedEmbedder

        return FastEmbedEmbedder(settings.embedding_model)
    if settings.embedding_provider == "voyage":
        from app.embeddings.voyage import VoyageEmbedder

        return VoyageEmbedder(settings.voyage_api_key, settings.embedding_model)
    return FakeEmbedder()


def build_reranker(settings: Settings) -> Reranker | None:
    if settings.reranker == "cross-encoder":
        from app.embeddings.fastembed_impl import CrossEncoderReranker

        return CrossEncoderReranker()
    if settings.reranker == "lexical":
        return LexicalReranker()
    return None


__all__ = ["Embedder", "FakeEmbedder", "LexicalReranker", "Reranker", "build_embedder", "build_reranker"]
