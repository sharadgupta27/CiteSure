"""Bundles the swappable providers. Built once at startup (API) or process start (worker)."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.embeddings import Embedder, Reranker, build_embedder, build_reranker
from app.llm import LLMProvider, build_llm, build_public_llm
from app.research import ResearchKit, build_kit
from app.storage.base import BlobStore, build_blob_store


@dataclass
class Providers:
    llm: LLMProvider  # INTERNAL lane: the only model that may read company documents
    embedder: Embedder
    reranker: Reranker | None
    blobs: BlobStore
    public_llm: LLMProvider | None = None  # PUBLIC lane: reads public text and cleared questions only
    research: ResearchKit | None = None  # the public research lane (None = disabled)


def build_providers(settings: Settings) -> Providers:
    public_llm = build_public_llm(settings)
    return Providers(
        llm=build_llm(settings),
        embedder=build_embedder(settings),
        reranker=build_reranker(settings),
        blobs=build_blob_store(settings),
        public_llm=public_llm,
        research=build_kit(settings, public_llm),
    )
