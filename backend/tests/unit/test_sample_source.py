"""The offline `sample` source: invented papers for browser tests, never network, never in production."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.research.connectors import SampleConnector, build_connectors
from app.research.sample_papers import SAMPLE_PAPERS


class NoNetwork:
    """Any use of the egress client fails the test: the sample source must not send anything."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the sample source touched the network client ({name})")


async def test_finds_the_matching_paper_first_without_touching_the_network() -> None:
    papers = await SampleConnector().search(NoNetwork(), "sparse attention memory long sequences", 5)  # type: ignore[arg-type]
    assert papers and papers[0].title == "[Sample] Sparse attention for long sequences"


async def test_unrelated_keywords_find_nothing_and_the_limit_is_kept() -> None:
    connector = SampleConnector()
    assert await connector.search(NoNetwork(), "volcano basalt", 5) == []  # type: ignore[arg-type]
    assert len(await connector.search(NoNetwork(), "retrieval search passages", 1)) == 1  # type: ignore[arg-type]


def test_sample_papers_cannot_pass_for_real_literature() -> None:
    for paper in SAMPLE_PAPERS:
        assert paper.title.startswith("[Sample]")
        assert paper.url.startswith("https://example.org/")
        assert paper.source == "sample"
        assert len(paper.text) >= 80  # long enough to be kept as evidence by the shared filter


def test_the_source_is_registered_by_name() -> None:
    assert [c.name for c in build_connectors(["sample"])] == ["sample"]


def test_production_refuses_the_sample_source() -> None:
    settings = Settings(
        env="prod",
        jwt_secret="p" * 48,
        public_research_enabled=True,
        public_sources="sample",
        public_llm_provider="fake",
    )
    with pytest.raises(RuntimeError, match="sample"):
        settings.assert_private_mode_consistent()
    Settings(
        public_research_enabled=True, public_sources="sample", public_llm_provider="fake"
    ).assert_private_mode_consistent()
