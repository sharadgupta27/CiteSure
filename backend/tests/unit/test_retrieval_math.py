"""Reciprocal Rank Fusion, tsquery building, fake embedder and reranker."""

from __future__ import annotations

import math
import uuid

import pytest

from app.embeddings.fake import FakeEmbedder, LexicalReranker
from app.rag.retrieval.fts import build_tsquery
from app.rag.retrieval.fusion import RRF_K, reciprocal_rank_fusion
from app.rag.retrieval.rerank import rerank
from app.rag.types import ScoredChunk


def chunk(name: str, text: str = "", score: float = 0.0) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_DNS, name),
        document_id=uuid.uuid4(),
        document_title=name,
        collection_id=uuid.uuid4(),
        ord=0,
        text=text or name,
        heading_path=[],
        page_start=None,
        page_end=None,
        char_start=0,
        char_end=len(text or name),
        score=score,
    )


def test_rrf_scores_follow_the_formula() -> None:
    a, b, c = chunk("a"), chunk("b"), chunk("c")
    fused = reciprocal_rank_fusion([[a, b], [b, c]])
    scores = {f.document_title: f.score for f in fused}
    assert scores["a"] == pytest.approx(1 / (RRF_K + 1))
    assert scores["b"] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert scores["c"] == pytest.approx(1 / (RRF_K + 2))
    assert [f.document_title for f in fused] == ["b", "a", "c"]


def test_rrf_ignores_the_raw_scores_of_the_input_lists() -> None:
    a, b = chunk("a", score=1000.0), chunk("b", score=0.001)
    assert [f.document_title for f in reciprocal_rank_fusion([[a, b]])] == ["a", "b"]


def test_rrf_limit_and_empty_inputs() -> None:
    items = [chunk(str(i)) for i in range(10)]
    assert len(reciprocal_rank_fusion([items], limit=3)) == 3
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_rrf_is_deterministic_on_ties() -> None:
    a, b = chunk("a"), chunk("b")
    first = [f.chunk_id for f in reciprocal_rank_fusion([[a], [b]])]
    second = [f.chunk_id for f in reciprocal_rank_fusion([[b], [a]])]
    assert first == second


def test_tsquery_keeps_only_safe_alphanumeric_terms() -> None:
    assert build_tsquery("How many weeks of leave?") == "how | many | weeks | of | leave"
    assert build_tsquery("'; DROP TABLE chunks; --") == "drop | table | chunks"
    assert build_tsquery("a & b | !c <-> (d)") == "a | b | c | d"
    assert build_tsquery("???") is None
    assert build_tsquery("") is None


async def test_fake_embedder_is_deterministic_normalised_and_lexical() -> None:
    embedder = FakeEmbedder()
    v1, v2 = await embedder.embed_documents(["parental leave weeks", "parental leave weeks"])
    assert v1 == v2
    assert len(v1) == embedder.dim == 384
    assert math.sqrt(sum(x * x for x in v1)) == pytest.approx(1.0)
    query = await embedder.embed_query("how many weeks of parental leave")
    related = await embedder.embed_documents(["Primary caregivers receive 16 weeks of paid parental leave."])
    unrelated = await embedder.embed_documents(["The robot arm e-stop is tested every week."])

    def cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert cosine(query, related[0]) > cosine(query, unrelated[0])


async def test_lexical_reranker_prefers_the_passage_that_answers() -> None:
    candidates = [
        chunk("noise", "Robots need an emergency stop test every week and a log entry."),
        chunk("answer", "Parental leave lasts 16 weeks for primary caregivers."),
        chunk("partial", "Leave requests are approved by the manager."),
    ]
    top = await rerank(LexicalReranker(), "how many weeks of parental leave", candidates, top_k=2)
    assert [c.document_title for c in top][0] == "answer"
    assert len(top) == 2


async def test_rerank_with_no_candidates() -> None:
    assert await rerank(LexicalReranker(), "anything", [], top_k=3) == []


def test_rrf_ties_do_not_depend_on_random_chunk_ids() -> None:
    """Regression: chunk ids are random per ingestion, so breaking ties on them made eval metrics change between identical runs."""

    def build() -> list[str]:
        a = ScoredChunk(uuid.uuid4(), uuid.uuid4(), "Alpha", uuid.uuid4(), 0, "a", [], None, None, 0, 1)
        b = ScoredChunk(uuid.uuid4(), uuid.uuid4(), "Beta", uuid.uuid4(), 0, "b", [], None, None, 0, 1)
        c = ScoredChunk(uuid.uuid4(), uuid.uuid4(), "Beta", uuid.uuid4(), 1, "c", [], None, None, 0, 1)
        # a, b and c each appear once at rank 1 of a different list: three-way tie
        fused = reciprocal_rank_fusion([[a], [b], [c]])
        return [f"{x.document_title}:{x.ord}" for x in fused]

    assert {tuple(build()) for _ in range(25)} == {("Alpha:0", "Beta:0", "Beta:1")}
