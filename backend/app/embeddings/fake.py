"""Deterministic offline stand-ins for the embedding model and the cross-encoder.

`FakeEmbedder` is a feature-hashing bag-of-words model: texts that share words get similar vectors.
It is not semantic (it will not match "vacation" to "PTO"), which is exactly why the evaluation can show
the value of hybrid search and why tests stay free, fast and reproducible.
"""

from __future__ import annotations

import hashlib
import math

from app.config import EMBEDDING_DIM
from app.rag.text import content_terms


def _bucket(token: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, 1.0 if (value >> 40) & 1 else -1.0


class FakeEmbedder:
    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        terms = content_terms(text)
        vector = [0.0] * self.dim
        counts: dict[str, float] = {}
        for term in terms:
            counts[term] = counts.get(term, 0.0) + 1.0
        for left, right in zip(terms, terms[1:], strict=False):  # bigrams reward phrase overlap
            key = f"{left}_{right}"
            counts[key] = counts.get(key, 0.0) + 0.5
        for token, count in counts.items():
            index, sign = _bucket(token, self.dim)
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class LexicalReranker:
    """Scores a passage by how many query terms and query bigrams it contains (a poor man's cross-encoder).

    It looks at the *pair* (query, passage) jointly, like a real cross-encoder, which is why it can reorder
    the fused candidates and improve precision at the top.
    """

    async def score(self, query: str, passages: list[str]) -> list[float]:
        q_terms = content_terms(query)
        if not q_terms:
            return [0.0] * len(passages)
        q_set = set(q_terms)
        q_bigrams = set(zip(q_terms, q_terms[1:], strict=False))
        scores: list[float] = []
        for passage in passages:
            p_terms = content_terms(passage)
            p_set = set(p_terms)
            coverage = len(q_set & p_set) / len(q_set)
            bigram_hits = len(q_bigrams & set(zip(p_terms, p_terms[1:], strict=False)))
            bigram_score = bigram_hits / len(q_bigrams) if q_bigrams else 0.0
            density = len(q_set & p_set) / math.sqrt(len(p_set) or 1)
            scores.append(coverage + 0.5 * bigram_score + 0.1 * density)
        return scores
