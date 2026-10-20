"""Bundles the swappable providers. Built once at startup (API) or process start (worker)."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.embeddings import Embedder, Reranker, build_embedder, build_reranker
from app.llm import LLMProvider, build_llm
from app.storage.base import BlobStore, build_blob_store


@dataclass
class Providers:
    llm: LLMProvider
    embedder: Embedder
    reranker: Reranker | None
    blobs: BlobStore


def build_providers(settings: Settings) -> Providers:
    return Providers(
        llm=build_llm(settings),
        embedder=build_embedder(settings),
        reranker=build_reranker(settings),
        blobs=build_blob_store(settings),
    )
