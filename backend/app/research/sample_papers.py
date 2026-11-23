"""Invented papers for the offline `sample` source (PUBLIC_SOURCES=sample).

They let the public lane run end to end with no internet: the browser tests in CI and local demos use them. Every title
starts with "[Sample]" and every address is on example.org, so they can never be mistaken for real literature.
The production check in `config.py` refuses this source when ENV=prod.
"""

from __future__ import annotations

from app.research.papers import Paper

SAMPLE_PAPERS: tuple[Paper, ...] = (
    Paper(
        source="sample",
        title="[Sample] Sparse attention for long sequences",
        text=(
            "Sparse attention reduces memory use for long sequences by letting each token attend to a fixed window of "
            "neighbours plus a few global tokens. Memory then grows linearly with sequence length instead of "
            "quadratically, which allows inputs of 16,000 tokens on a single GPU."
        ),
        url="https://example.org/citesure-sample/sparse-attention",
        authors=("Ada Lindqvist", "Tomas Ferreira"),
        year=2025,
    ),
    Paper(
        source="sample",
        title="[Sample] Evaluating retrieval augmented generation with golden questions",
        text=(
            "Retrieval augmented generation should be evaluated with a fixed set of golden questions written before the "
            "system is built. Recall at k measures whether the right passages are retrieved, and citation precision "
            "measures whether the cited passages support each claim."
        ),
        url="https://example.org/citesure-sample/rag-evaluation",
        authors=("Mei Okafor",),
        year=2024,
    ),
    Paper(
        source="sample",
        title="[Sample] Hybrid search with reciprocal rank fusion",
        text=(
            "Hybrid search combines keyword search and vector search. Reciprocal rank fusion merges the two ranked lists "
            "without normalising their scores, and a cross-encoder reranker applied afterwards puts the most relevant "
            "passage first more often than either list alone."
        ),
        url="https://example.org/citesure-sample/hybrid-search",
        authors=("Jonas Weber", "Priya Raman", "Lena Costa"),
        year=2025,
    ),
)
