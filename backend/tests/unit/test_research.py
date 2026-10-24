"""The public lane: connector parsers on recorded-shape payloads, query building, and the search service with a mock
network. Nothing here touches the internet."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings
from app.egress.client import EgressClient
from app.embeddings.fake import LexicalReranker
from app.research.connectors import (
    ArxivConnector,
    build_connectors,
    parse_arxiv,
    parse_crossref,
    parse_europepmc,
    parse_openalex,
    parse_semantic_scholar,
    rebuild_abstract,
)
from app.research.papers import Paper
from app.research.query import build_public_query
from app.research.service import PublicResearch, ResearchKit
from tests.unit.test_egress_guard import FakeCorpus

ABSTRACT = (
    "We study sparse attention for long sequences and show that block-sparse patterns reduce memory use "
    "by forty percent while keeping accuracy within one point of dense attention."
)

ARXIV = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Block-Sparse Attention
      for Long Sequences</title>
    <summary>{ABSTRACT}</summary>
    <published>2024-01-02T00:00:00Z</published>
    <author><name>Ada Lovelace</name></author><author><name>Alan Turing</name></author>
  </entry>
  <entry><id>http://arxiv.org/abs/2401.00002v1</id><title>Stub</title><summary>too short</summary></entry>
</feed>""".encode()

CROSSREF = json.dumps(
    {
        "message": {
            "items": [
                {
                    "DOI": "10.1000/abc",
                    "title": ["Sparse attention, revisited"],
                    "abstract": f"<jats:p>{ABSTRACT}</jats:p>",
                    "author": [{"given": "Grace", "family": "Hopper"}],
                    "issued": {"date-parts": [[2023, 5]]},
                    "URL": "https://doi.org/10.1000/abc",
                },
                {"DOI": "10.1000/noabs", "title": ["No abstract"], "URL": "https://doi.org/10.1000/noabs"},
            ]
        }
    }
).encode()

OPENALEX = json.dumps(
    {
        "results": [
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1000/abc",
                "display_name": "Sparse attention, revisited",
                "publication_year": 2023,
                "authorships": [{"author": {"display_name": "Grace Hopper"}}],
                "abstract_inverted_index": {w: [i] for i, w in enumerate(ABSTRACT.split())},
            }
        ]
    }
).encode()

EUROPEPMC = json.dumps(
    {
        "resultList": {
            "result": [
                {
                    "id": "123",
                    "source": "MED",
                    "title": "Attention in clinical notes",
                    "abstractText": f"<h4>Background</h4>{ABSTRACT}",
                    "authorString": "Smith J, Jones K.",
                    "pubYear": "2022",
                    "doi": "10.2000/xyz",
                }
            ]
        }
    }
).encode()

SEMANTIC = json.dumps(
    {
        "data": [
            {
                "title": "Efficient attention",
                "abstract": ABSTRACT,
                "year": 2021,
                "url": "https://www.semanticscholar.org/paper/1",
                "authors": [{"name": "Ada Lovelace"}],
                "externalIds": {"DOI": "10.3000/s2"},
            }
        ]
    }
).encode()


def test_arxiv_parser_keeps_real_abstracts_and_drops_stubs() -> None:
    papers = parse_arxiv(ARXIV)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "Block-Sparse Attention for Long Sequences"
    assert paper.url == "https://arxiv.org/abs/2401.00001v1" and paper.year == 2024
    assert paper.authors == ("Ada Lovelace", "Alan Turing")
    assert paper.label == "Block-Sparse Attention for Long Sequences (Lovelace et al., 2024)"


def test_arxiv_parser_refuses_documents_with_a_dtd() -> None:
    hostile = b'<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY a "aaaa">]><feed xmlns="http://www.w3.org/2005/Atom"/>'
    try:
        parse_arxiv(hostile)
    except ValueError:
        return
    raise AssertionError("a DTD must be rejected")


def test_crossref_strips_jats_markup_and_skips_records_without_abstracts() -> None:
    papers = parse_crossref(CROSSREF)
    assert [p.doi for p in papers] == ["10.1000/abc"]
    assert "<" not in papers[0].text and papers[0].year == 2023 and papers[0].authors == ("Grace Hopper",)


def test_openalex_rebuilds_the_abstract_from_the_inverted_index() -> None:
    assert rebuild_abstract({"b": [1], "a": [0], "c": [2]}) == "a b c"
    assert rebuild_abstract(None) == ""
    paper = parse_openalex(OPENALEX)[0]
    assert paper.text == " ".join(ABSTRACT.split()) and paper.doi == "https://doi.org/10.1000/abc"


def test_europepmc_and_semantic_scholar_parsers() -> None:
    pmc = parse_europepmc(EUROPEPMC)[0]
    assert pmc.url == "https://europepmc.org/article/MED/123" and pmc.text.startswith("Background")
    assert pmc.authors == ("Smith J", "Jones K")
    assert parse_semantic_scholar(SEMANTIC)[0].doi == "10.3000/s2"


def test_the_same_paper_from_two_sources_gets_one_identity() -> None:
    crossref, openalex = parse_crossref(CROSSREF)[0], parse_openalex(OPENALEX)[0]
    assert crossref.key == openalex.key
    assert crossref.to_chunk().chunk_id == openalex.to_chunk().chunk_id


def test_public_chunks_are_marked_public_and_carry_their_address() -> None:
    chunk = parse_crossref(CROSSREF)[0].to_chunk()
    assert chunk.source_type == "public" and chunk.url == "https://doi.org/10.1000/abc"
    assert chunk.char_end == len(chunk.text) and chunk.heading_path == ["Sparse attention, revisited"]


def test_query_builder_keeps_keywords_only() -> None:
    query = build_public_query("Please explain how sparse attention reduces memory for long sequences in transformers?")
    assert query == "sparse attention reduces memory sequences transformers"
    assert build_public_query("the of and to") == ""
    assert len(build_public_query("alpha bravo charlie delta echo foxtrot golf hotel india juliet").split()) == 8


def test_unknown_source_names_are_rejected_at_startup() -> None:
    try:
        build_connectors(["arxiv", "bing"])
    except RuntimeError as exc:
        assert "bing" in str(exc)
        return
    raise AssertionError("unknown source accepted")


# --- the service, with a mock network --------------------------------------------------------------------------------
def mock_network(sent: list[httpx.Request], *, fail: str | None = None) -> httpx.MockTransport:
    bodies: dict[str, bytes] = {
        "export.arxiv.org": ARXIV,
        "api.crossref.org": CROSSREF,
        "api.openalex.org": OPENALEX,
        "www.ebi.ac.uk": EUROPEPMC,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if fail and request.url.host == fail:
            raise httpx.ConnectError("source is down")
        return httpx.Response(200, content=bodies[request.url.host])

    return httpx.MockTransport(handler)


def research(
    sent: list[httpx.Request], corpus: FakeCorpus | None = None, *, fail: str | None = None, **settings: Any
) -> PublicResearch:
    config = Settings(env="test", public_research_enabled=True, **settings)
    client = EgressClient(
        mode="allowlist",
        allow_hosts=config.egress_allow_host_list,
        user_agent="t",
        timeout_s=5,
        max_bytes=500_000,
        check_dns=False,
        transport=mock_network(sent, fail=fail),
    )
    kit = ResearchKit(config, client, build_connectors(config.public_source_list))
    return kit.for_request(corpus)


async def test_search_queries_every_source_with_the_keywords_only() -> None:
    sent: list[httpx.Request] = []
    result = await research(sent).search("How does sparse attention reduce memory?", reranker=LexicalReranker())
    assert result.query == "sparse attention reduce memory"
    assert {r.destination for r in result.records} == {"arxiv", "crossref", "openalex", "europepmc"}
    assert all(r.status == "sent" and r.query == result.query for r in result.records)
    assert len(sent) == 4
    for request in sent:  # the only user-derived text on the wire is the keyword query
        assert "How does" not in str(request.url) and "?" not in request.url.params.get("query", "")
    assert result.chunks and all(c.source_type == "public" and c.url for c in result.chunks)
    assert len({c.chunk_id for c in result.chunks}) == len(result.chunks)  # duplicates across sources were merged
    assert result.question_cleared


async def test_a_blocked_query_sends_nothing_and_explains_why() -> None:
    sent: list[httpx.Request] = []
    result = await research(sent, egress_deny_terms="Phoenix").search("What did Project Phoenix conclude about attention?")
    assert sent == [] and result.chunks == [] and not result.question_cleared
    assert [r.status for r in result.records] == ["blocked"] and result.records[0].query is None
    assert "company-sensitive content" in result.notices[0] and "Phoenix" not in result.notices[0]
    assert "Phoenix" not in (result.records[0].reason or "")


async def test_personal_data_in_the_question_stops_the_search_even_though_keywords_would_pass() -> None:
    sent: list[httpx.Request] = []
    result = await research(sent).search("Does jane.doe@acme.com know about sparse attention research?")
    assert sent == [] and "personal data" in result.notices[0]


async def test_an_edited_query_replaces_the_derived_one_and_is_still_checked() -> None:
    sent: list[httpx.Request] = []
    result = await research(sent).search("What did Project Phoenix conclude?", explicit_query="sparse attention efficiency")
    assert result.query == "sparse attention efficiency" and len(sent) == 4
    blocked_sent: list[httpx.Request] = []
    blocked = await research(blocked_sent, egress_canaries="CANARY-1").search("q q q", explicit_query="CANARY-1 attention")
    assert blocked_sent == [] and blocked.records[0].status == "blocked"


async def test_one_failing_source_is_reported_and_the_rest_still_answer() -> None:
    sent: list[httpx.Request] = []
    result = await research(sent, fail="export.arxiv.org").search("sparse attention memory")
    statuses = {r.destination: r.status for r in result.records}
    assert statuses["arxiv"] == "failed" and statuses["crossref"] == "sent"
    assert result.chunks and "did not respond: arxiv" in result.notices[0]


async def test_preview_sends_nothing() -> None:
    sent: list[httpx.Request] = []
    preview = await research(sent, egress_deny_terms="Phoenix").preview("Is Phoenix mentioned in attention papers?")
    assert sent == [] and not preview.allowed and preview.reasons == ("company_content",)
    ok = await research(sent).preview("sparse attention memory")
    assert ok.allowed and ok.query == "sparse attention memory" and sent == []


async def test_text_copied_from_a_document_cannot_leave_even_as_the_query() -> None:
    internal = "the quarterly retention formula multiplies weekly active seats by the churn coefficient"
    sent: list[httpx.Request] = []
    result = await research(sent, FakeCorpus([internal])).search(
        "retention formula multiplies weekly active seats by the churn", explicit_query=internal
    )
    assert sent == [] and "company-sensitive content" in result.notices[0]
    assert "copied" not in result.notices[0] and "document" not in result.notices[0]


async def test_arxiv_connector_builds_an_and_query_of_at_most_four_terms() -> None:
    sent: list[httpx.Request] = []
    config = Settings(env="test")
    client = EgressClient(
        mode="allowlist",
        allow_hosts=config.egress_allow_host_list,
        user_agent="t",
        timeout_s=5,
        max_bytes=500_000,
        check_dns=False,
        transport=mock_network(sent),
    )
    await ArxivConnector().search(client, "one two three four five six", 3)
    assert sent[0].url.params["search_query"] == "all:one AND all:two AND all:three AND all:four"
    assert sent[0].url.params["max_results"] == "3"


def test_paper_label_without_authors_or_year() -> None:
    assert Paper(source="web", title="Page", text="x", url="https://e.org").label == "Page"
