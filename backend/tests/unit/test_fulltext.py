"""Open-access full text: identifying a paper, finding and fetching its PDF through the egress client, turning it into
passages, and using the cache in the public lane. A mock transport stands in for the whole internet."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pymupdf
import pytest

from app.config import Settings
from app.egress.client import EgressClient
from app.embeddings.fake import LexicalReranker
from app.rag.types import ScoredChunk
from app.research.connectors import (
    build_connectors,
    europepmc_oa_url,
    openalex_oa_urls,
    parse_arxiv,
    parse_europepmc,
    parse_openalex,
    parse_semantic_scholar,
)
from app.research.fulltext import (
    FullTextError,
    OpenAccessFinder,
    Trail,
    build_passages,
    clean_doi,
    fetch_pdf,
    find_and_fetch,
    identify,
)
from app.research.papers import PUBLIC_COLLECTION_ID, Paper
from app.research.service import ResearchKit
from tests.unit.test_research import ABSTRACT, ARXIV, EUROPEPMC, OPENALEX, SEMANTIC, mock_network

SETTINGS = Settings(env="test", public_research_enabled=True)
OPENALEX_WORK_URL = "https://api.openalex.org/works/doi:10.1000/abc"


def paper_pdf(pages: int = 2, sentence: str = "Block sparse attention reduces memory use by forty percent.") -> bytes:
    doc = pymupdf.open()
    for number in range(1, pages + 1):
        page = doc.new_page()
        page.insert_text((72, 72), f"{number} Results", fontsize=14)
        for line in range(12):
            page.insert_text(
                (72, 110 + line * 16), f"{sentence} Observation {number}.{line} holds on every benchmark.", fontsize=9
            )
    return doc.tobytes()


PDF = paper_pdf()


class Net:
    """A scripted internet: routes by `host/path` prefix, remembers every request that reached the transport."""

    def __init__(self, routes: dict[str, Callable[[httpx.Request], httpx.Response] | httpx.Response]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.url.host}{request.url.path}"
        for prefix, reply in self.routes.items():
            if key.startswith(prefix):
                return reply(request) if callable(reply) else reply
        return httpx.Response(404)

    @property
    def hosts(self) -> list[str]:
        return [r.url.host for r in self.requests]


def pdf_reply(content: bytes = PDF, content_type: str = "application/pdf") -> httpx.Response:
    return httpx.Response(200, content=content, headers={"content-type": content_type})


def client_for(net: Net, **overrides: Any) -> EgressClient:
    options: dict[str, Any] = {
        "mode": "allowlist",
        "allow_hosts": SETTINGS.egress_allow_host_list,
        "user_agent": "t",
        "timeout_s": 5,
        "max_bytes": 500_000,
        "check_dns": False,
        "transport": httpx.MockTransport(net),
    }
    return EgressClient(**{**options, **overrides})


def openalex_work(**extra: Any) -> httpx.Response:
    work = {
        "id": "https://openalex.org/W1",
        "doi": "https://doi.org/10.1000/abc",
        "display_name": "Sparse attention, revisited",
        "publication_year": 2023,
        "authorships": [{"author": {"display_name": "Grace Hopper"}}],
        **extra,
    }
    return httpx.Response(200, content=json.dumps(work).encode())


# --- identifying the paper -----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "doi", "key"),
    [
        ("https://doi.org/10.1000/ABC", None, "doi:10.1000/abc"),
        ("http://dx.doi.org/10.1038/s41586-020-2649-2", None, "doi:10.1038/s41586-020-2649-2"),
        ("https://example.org/ignored", "https://doi.org/10.1000/abc", "doi:10.1000/abc"),
        ("https://example.org/ignored", "DOI:10.1000/abc", "doi:10.1000/abc"),
        ("https://arxiv.org/abs/2401.00001v1", None, "arxiv:2401.00001"),
        ("https://arxiv.org/pdf/2401.00001v2.pdf", None, "arxiv:2401.00001"),
        ("https://arxiv.org/abs/hep-th/9901001", None, "arxiv:hep-th/9901001"),
        ("https://export.arxiv.org/abs/2401.00001", None, "arxiv:2401.00001"),
        ("https://europepmc.org/article/MED/123", None, "europepmc:MED/123"),
        ("https://europepmc.org/article/PMC/PMC1234567", None, "europepmc:PMC/PMC1234567"),
        ("https://openalex.org/W2741809807", None, "openalex:W2741809807"),
        ("https://doi.org/10.48550/arXiv.2401.00001", None, "doi:10.48550/arxiv.2401.00001"),
    ],
)
def test_a_citation_address_names_the_paper(url: str, doi: str | None, key: str) -> None:
    assert identify(url, doi).key == key


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/blog/post",  # an arbitrary web page is not a paper
        "javascript:alert(1)",
        "ftp://arxiv.org/abs/2401.00001",
        "https://arxiv.org/abs/../../etc/passwd",
        "https://arxiv.org/list/cs.AI/recent",
        "https://doi.org/not-a-doi",
        "https://doi.org/10.1000/has space",
        "https://doi.org/10.1000/a/../../b",
        "https://europepmc.org/search?query=secret",
        "https://openalex.org/authors/A1",
        "https://evil.example/https://doi.org/10.1000/abc",
        "",
    ],
)
def test_addresses_that_name_no_paper_are_refused(url: str) -> None:
    with pytest.raises(FullTextError) as caught:
        identify(url)
    assert caught.value.code == "unsupported_source"


def test_a_doi_field_that_is_not_a_doi_is_refused_not_sent() -> None:
    with pytest.raises(FullTextError):
        identify("https://doi.org/10.1000/abc", "Project Phoenix budget 2027 notes")


def test_a_doi_that_is_an_arxiv_doi_also_names_the_arxiv_copy() -> None:
    assert identify("https://doi.org/10.48550/arXiv.2401.00001").arxiv_id == "2401.00001"
    assert clean_doi("https://doi.org/10.1000/ABC%2Fdef") == "10.1000/abc/def"


# --- open-access locations in search results -----------------------------------------------------------------------
def test_search_results_carry_the_open_access_location_the_source_reports() -> None:
    assert parse_arxiv(ARXIV)[0].oa_url == "https://arxiv.org/pdf/2401.00001v1"
    assert parse_openalex(OPENALEX)[0].oa_url is None  # the fixture has no open-access fields

    work = {
        "best_oa_location": {"pdf_url": "https://repo.example/a.pdf"},
        "open_access": {"oa_url": "https://publisher.example/landing"},
        "locations": [
            {"is_oa": True, "pdf_url": "https://other.example/b.pdf"},
            {"is_oa": False, "pdf_url": "https://closed.example/c.pdf"},
            {"is_oa": True, "pdf_url": "http://insecure.example/d.pdf"},
        ],
    }
    assert openalex_oa_urls(work) == [
        "https://repo.example/a.pdf",
        "https://publisher.example/landing",
        "https://other.example/b.pdf",
    ]


def test_europepmc_and_semantic_scholar_report_open_access_pdfs() -> None:
    listed = {
        "fullTextUrlList": {
            "fullTextUrl": [{"url": "https://europepmc.org/x.pdf", "documentStyle": "pdf", "availabilityCode": "OA"}]
        }
    }
    assert europepmc_oa_url(listed) == "https://europepmc.org/x.pdf"
    assert europepmc_oa_url({"isOpenAccess": "Y", "pmcid": "PMC123"}).endswith("accid=PMC123&blobtype=pdf")  # type: ignore[union-attr]
    assert europepmc_oa_url({"isOpenAccess": "Y", "pmcid": "PMC123/../x"}) is None
    assert europepmc_oa_url({"isOpenAccess": "N", "pmcid": "PMC123"}) is None
    assert parse_europepmc(EUROPEPMC)[0].oa_url is None

    payload = json.loads(SEMANTIC)
    payload["data"][0]["openAccessPdf"] = {"url": "https://s2.example/p.pdf"}
    assert parse_semantic_scholar(json.dumps(payload).encode())[0].oa_url == "https://s2.example/p.pdf"
    assert parse_semantic_scholar(SEMANTIC)[0].oa_url is None


# --- fetching a PDF ------------------------------------------------------------------------------------------------
async def fetch(net: Net, url: str = "https://arxiv.org/pdf/2401.00001", **client_options: Any) -> tuple[Trail, Any]:
    trail = Trail("arXiv:2401.00001")
    client = client_for(net, **client_options)
    try:
        return trail, await fetch_pdf(client, SETTINGS, url, trail)
    finally:
        await client.aclose()


async def test_a_real_pdf_is_fetched_and_recorded() -> None:
    net = Net({"arxiv.org/pdf/": pdf_reply()})
    trail, pdf = await fetch(net)
    assert pdf.data == PDF and pdf.host == "arxiv.org" and len(pdf.sha256) == 64
    assert [(r.destination, r.status, r.query) for r in trail.records] == [("arxiv.org", "sent", "arXiv:2401.00001")]
    assert net.requests[0].headers["accept"] == "application/pdf"


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (httpx.Response(200, content=b"<html>Paywall</html>", headers={"content-type": "text/html"}), "not_pdf"),
        (httpx.Response(200, content=b"<html>Paywall</html>", headers={"content-type": "application/pdf"}), "not_pdf"),
        (httpx.Response(200, content=PDF, headers={"content-type": "text/html"}), "not_pdf"),
        (httpx.Response(404), "fetch_failed"),
        (httpx.Response(503), "fetch_failed"),
    ],
)
async def test_anything_that_is_not_a_pdf_is_refused_and_recorded_as_failed(reply: httpx.Response, code: str) -> None:
    trail = Trail("x")
    client = client_for(Net({"arxiv.org/": reply}))
    with pytest.raises(FullTextError) as caught:
        await fetch_pdf(client, SETTINGS, "https://arxiv.org/pdf/2401.00001", trail)
    assert caught.value.code == code
    assert [r.status for r in trail.records] == ["failed"]


async def test_octet_stream_is_accepted_only_when_the_content_is_a_pdf() -> None:
    _, pdf = await fetch(Net({"arxiv.org/": pdf_reply(content_type="application/octet-stream")}))
    assert pdf.data.startswith(b"%PDF-")
    with pytest.raises(FullTextError):
        await fetch(Net({"arxiv.org/": pdf_reply(b"MZ\x90\x00not a pdf", "application/octet-stream")}))


async def test_a_download_over_the_byte_cap_is_cut_off_and_reported_as_too_large() -> None:
    settings = Settings(env="test", fulltext_max_bytes=100_000)
    big = pdf_reply(b"%PDF-1.7\n" + b"0" * 150_000)
    for reply in (
        big,
        httpx.Response(200, content=big.content, headers={"content-type": "application/pdf", "content-length": "150009"}),
    ):
        trail = Trail("x")
        client = client_for(Net({"arxiv.org/": reply}))
        with pytest.raises(FullTextError) as caught:
            await fetch_pdf(client, settings, "https://arxiv.org/pdf/1", trail)
        assert caught.value.code == "too_large" and trail.records[0].status == "blocked"


async def test_hosts_outside_the_allow_list_are_never_contacted() -> None:
    net = Net({"": pdf_reply()})
    trail = Trail("x")
    with pytest.raises(FullTextError) as caught:
        await fetch_pdf(client_for(net), SETTINGS, "https://publisher.example/paper.pdf", trail)
    assert caught.value.code == "host_not_allowed" and net.requests == []
    assert [(r.destination, r.status, r.reason, r.query) for r in trail.records] == [
        ("publisher.example", "blocked", "not_allowed", None)
    ]


@pytest.mark.parametrize(
    "url",
    ["http://arxiv.org/pdf/1", "https://user:pw@arxiv.org/pdf/1", "https://127.0.0.1/a.pdf", "https://localhost/a.pdf"],
)
async def test_unsafe_addresses_are_refused_before_sending(url: str) -> None:
    net = Net({"": pdf_reply()})
    with pytest.raises(FullTextError):
        await fetch_pdf(client_for(net), SETTINGS, url, Trail("x"))
    assert net.requests == []


async def test_a_redirect_to_a_private_or_unlisted_address_is_not_followed() -> None:
    for location, reason in (
        ("https://169.254.169.254/latest/meta-data", "private_address"),
        ("https://evil.example/x.pdf", "not_allowed"),
    ):
        net = Net({"arxiv.org/": httpx.Response(302, headers={"location": location})})
        trail = Trail("x")
        with pytest.raises(FullTextError):
            await fetch_pdf(client_for(net), SETTINGS, "https://arxiv.org/pdf/1", trail)
        assert net.hosts == ["arxiv.org"]  # the second hop was never sent
        assert trail.records[0].reason == reason


async def test_a_redirect_between_allowed_hosts_is_followed() -> None:
    net = Net(
        {
            "arxiv.org/pdf": httpx.Response(302, headers={"location": "https://europepmc.org/real.pdf"}),
            "europepmc.org/": pdf_reply(),
        }
    )
    _, pdf = await fetch(net)
    assert pdf.data == PDF and net.hosts == ["arxiv.org", "europepmc.org"]


async def test_a_slow_download_is_stopped_at_the_time_limit() -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return pdf_reply()

    settings = Settings(env="test", fulltext_timeout_s=0.05)
    trail = Trail("x")
    client = client_for(Net({}), transport=httpx.MockTransport(slow))
    with pytest.raises(FullTextError) as caught:
        await fetch_pdf(client, settings, "https://arxiv.org/pdf/1", trail)
    assert caught.value.code == "timeout" and trail.records[0].reason == "timeout"


# --- finding the PDF -----------------------------------------------------------------------------------------------
async def run_find(net: Net, url: str, doi: str | None = None, **settings: Any) -> tuple[Any, OpenAccessFinder, Trail]:
    config = Settings(env="test", public_research_enabled=True, **settings)
    ref = identify(url, doi)
    trail = Trail(ref.identifier)
    client = client_for(net, allow_hosts=config.egress_allow_host_list)
    finder = OpenAccessFinder(client, config, trail)
    try:
        return await find_and_fetch(client, config, finder, ref, trail), finder, trail
    finally:
        await client.aclose()


async def test_an_arxiv_paper_is_fetched_from_arxiv_and_named_by_its_feed() -> None:
    net = Net({"export.arxiv.org/api": httpx.Response(200, content=ARXIV), "arxiv.org/pdf/2401.00001": pdf_reply()})
    pdf, finder, trail = await run_find(net, "https://arxiv.org/abs/2401.00001v1")
    assert pdf.data == PDF and finder.meta.title == "Block-Sparse Attention for Long Sequences"
    assert net.requests[0].url.params["id_list"] == "2401.00001"
    assert [(r.destination, r.status) for r in trail.records] == [("export.arxiv.org", "sent"), ("arxiv.org", "sent")]


async def test_a_doi_uses_openalex_and_falls_through_a_landing_page_to_the_real_pdf() -> None:
    work = openalex_work(
        best_oa_location={"pdf_url": "https://europepmc.org/landing"},
        open_access={"oa_url": "https://arxiv.org/pdf/2401.00001"},
    )
    net = Net(
        {
            "api.openalex.org/works/doi:10.1000/abc": work,
            "europepmc.org/landing": httpx.Response(200, content=b"<html/>", headers={"content-type": "text/html"}),
            "arxiv.org/pdf": pdf_reply(),
        }
    )
    pdf, finder, trail = await run_find(net, "https://doi.org/10.1000/abc")
    assert pdf.host == "arxiv.org" and finder.meta.title == "Sparse attention, revisited" and finder.meta.year == 2023
    assert [(r.destination, r.status, r.reason) for r in trail.records] == [
        ("api.openalex.org", "sent", None),
        ("europepmc.org", "failed", "not_pdf"),
        ("arxiv.org", "sent", None),
    ]
    assert all(r.query == "10.1000/abc" for r in trail.records)  # only the public identifier went out
    assert net.requests[0].url.params["select"].startswith("id,doi")


async def test_the_next_source_is_asked_when_one_has_no_open_access_copy() -> None:
    net = Net(
        {
            "api.openalex.org/": openalex_work(),
            "api.semanticscholar.org/graph/v1/paper/DOI:10.1000/abc": httpx.Response(
                200, content=json.dumps({"title": "T", "openAccessPdf": {"url": "https://arxiv.org/pdf/9"}}).encode()
            ),
            "arxiv.org/pdf/9": pdf_reply(),
        }
    )
    pdf, _, _ = await run_find(net, "https://doi.org/10.1000/abc")
    assert pdf.url.endswith("/pdf/9")
    assert net.hosts == ["api.openalex.org", "api.semanticscholar.org", "arxiv.org"]


async def test_europepmc_supplies_the_pdf_for_a_pmc_article() -> None:
    record = {"title": "Clinical attention", "pubYear": "2022", "isOpenAccess": "Y", "pmcid": "PMC123"}
    net = Net(
        {
            "www.ebi.ac.uk/europepmc/webservices/rest/search": httpx.Response(
                200, content=json.dumps({"resultList": {"result": [record]}}).encode()
            ),
            "europepmc.org/backend/ptpmcrender.fcgi": pdf_reply(),
        }
    )
    pdf, finder, _ = await run_find(net, "https://europepmc.org/article/MED/123")
    assert pdf.host == "europepmc.org" and finder.meta.title == "Clinical attention"
    assert net.requests[0].url.params["query"] == "EXT_ID:123 AND SRC:MED"


async def test_only_the_enabled_sources_are_asked() -> None:
    net = Net(
        {
            "api.openalex.org/": openalex_work(open_access={"oa_url": "https://arxiv.org/pdf/1"}),
            "arxiv.org/pdf/1": pdf_reply(),
        }
    )
    await run_find(net, "https://doi.org/10.1000/abc", public_sources="openalex")
    assert set(net.hosts) == {"api.openalex.org", "arxiv.org"}
    silent = Net({})
    with pytest.raises(FullTextError) as caught:
        await run_find(silent, "https://doi.org/10.1000/abc", public_sources="crossref")
    assert caught.value.code == "no_open_access" and silent.requests == []


async def test_no_open_access_copy_is_a_clear_error() -> None:
    net = Net(
        {
            "api.openalex.org/": openalex_work(),
            "api.semanticscholar.org/": httpx.Response(404),
            "www.ebi.ac.uk/": httpx.Response(200, content=b'{"resultList":{"result":[]}}'),
        }
    )
    with pytest.raises(FullTextError) as caught:
        await run_find(net, "https://doi.org/10.1000/abc")
    assert caught.value.code == "no_open_access"


async def test_a_copy_on_an_unlisted_host_is_reported_as_such_and_never_contacted() -> None:
    net = Net({"api.openalex.org/": openalex_work(best_oa_location={"pdf_url": "https://publisher.example/p.pdf"})})
    with pytest.raises(FullTextError) as caught:
        await run_find(net, "https://doi.org/10.1000/abc", public_sources="openalex")
    assert caught.value.code == "host_not_allowed"
    assert "publisher.example" not in net.hosts


async def test_at_most_four_candidate_addresses_are_tried() -> None:
    urls = [f"https://arxiv.org/pdf/{n}" for n in range(1, 9)]
    net = Net(
        {
            "api.openalex.org/": openalex_work(locations=[{"is_oa": True, "pdf_url": u} for u in urls]),
            "arxiv.org/": httpx.Response(404),
        }
    )
    with pytest.raises(FullTextError):
        await run_find(net, "https://doi.org/10.1000/abc", public_sources="openalex")
    assert net.hosts.count("arxiv.org") == 4


# --- parsing and chunking ------------------------------------------------------------------------------------------
async def test_a_paper_becomes_page_numbered_passages_with_exact_offsets() -> None:
    passages = await build_passages(paper_pdf(3), SETTINGS, "Sparse attention, revisited")
    assert passages.title == "Sparse attention, revisited" and passages.page_count == 3
    assert passages.drafts and min(d.page_start or 99 for d in passages.drafts) == 1
    assert max(d.page_end or 0 for d in passages.drafts) == 3
    assert all(d.page_start is not None and d.page_end is not None and d.char_end > d.char_start for d in passages.drafts)
    assert any("forty percent" in d.text for d in passages.drafts)


async def test_a_pdf_with_too_many_pages_is_refused_before_it_is_parsed() -> None:
    with pytest.raises(FullTextError) as caught:
        await build_passages(paper_pdf(4), Settings(env="test", fulltext_max_pages=3), "T")
    assert caught.value.code == "too_long"


async def test_a_pdf_with_too_many_passages_is_refused() -> None:
    with pytest.raises(FullTextError) as caught:
        await build_passages(paper_pdf(3), Settings(env="test", fulltext_max_chunks=10, chunk_tokens=40), "T")
    assert caught.value.code == "too_long"


@pytest.mark.parametrize("data", [b"%PDF-1.7 garbage", b"not a pdf at all", b""])
async def test_damaged_files_are_unreadable(data: bytes) -> None:
    with pytest.raises(FullTextError) as caught:
        await build_passages(data, SETTINGS, "T")
    assert caught.value.code == "unreadable"


async def test_a_pdf_without_text_is_unreadable() -> None:
    blank = pymupdf.open()
    blank.new_page()
    with pytest.raises(FullTextError) as caught:
        await build_passages(blank.tobytes(), SETTINGS, "T")
    assert caught.value.code == "unreadable"


async def test_an_encrypted_pdf_is_unreadable() -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Secret contents of the paper.")
    locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(FullTextError) as caught:
        await build_passages(locked, SETTINGS, "T")
    assert caught.value.code == "unreadable"


# --- the public lane uses the cache -------------------------------------------------------------------------------
def cached_chunk(text: str = "Block sparse attention reduces memory use by forty percent on page three.") -> ScoredChunk:
    return ScoredChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Sparse attention, revisited (Hopper, 2023)",
        collection_id=PUBLIC_COLLECTION_ID,
        ord=4,
        text=text,
        heading_path=["3 Results"],
        page_start=3,
        page_end=3,
        char_start=100,
        char_end=100 + len(text),
        source_type="public",
        url="https://doi.org/10.1000/abc",
    )


class FakeIndex:
    def __init__(self, chunks: list[ScoredChunk] | None = None, error: Exception | None = None) -> None:
        self.chunks, self.error, self.calls = chunks or [], error, []

    async def search(self, question: str, limit: int) -> list[ScoredChunk]:
        self.calls.append((question, limit))
        if self.error:
            raise self.error
        return self.chunks


def lane(index: FakeIndex | None, sent: list[httpx.Request], **settings: Any) -> Any:
    config = Settings(env="test", public_research_enabled=True, **settings)
    client = EgressClient(
        mode="allowlist",
        allow_hosts=config.egress_allow_host_list,
        user_agent="t",
        timeout_s=5,
        max_bytes=500_000,
        check_dns=False,
        transport=mock_network(sent),
    )
    return ResearchKit(config, client, build_connectors(config.public_source_list)).for_request(None, index)


async def test_cached_full_text_is_cited_alongside_abstracts_with_page_numbers() -> None:
    sent: list[httpx.Request] = []
    index = FakeIndex([cached_chunk()])
    result = await lane(index, sent).search("How does sparse attention reduce memory?", reranker=LexicalReranker())
    full_text = [c for c in result.chunks if c.page_start == 3]
    assert full_text and full_text[0].source_type == "public" and full_text[0].url == "https://doi.org/10.1000/abc"
    assert full_text[0].collection_id == PUBLIC_COLLECTION_ID
    assert any(c.page_start is None for c in result.chunks)  # the abstracts are still there
    assert index.calls and index.calls[0][0] == "How does sparse attention reduce memory?"
    assert len(sent) == 5  # the cache lookup added no request: it is local
    assert {r.destination for r in result.records} == {"arxiv", "crossref", "openalex", "europepmc", "semanticscholar"}


async def test_a_blocked_query_does_not_search_the_cache_either() -> None:
    sent: list[httpx.Request] = []
    index = FakeIndex([cached_chunk()])
    result = await lane(index, sent, egress_deny_terms="Phoenix").search("What did Project Phoenix conclude?")
    assert result.chunks == [] and index.calls == [] and sent == []


async def test_a_failing_cache_never_fails_the_answer() -> None:
    sent: list[httpx.Request] = []
    result = await lane(FakeIndex(error=RuntimeError("database is down")), sent).search("sparse attention memory")
    assert result.chunks and all(c.page_start is None for c in result.chunks)


async def test_without_a_cache_the_lane_behaves_as_before() -> None:
    sent: list[httpx.Request] = []
    result = await lane(None, sent).search("sparse attention memory")
    assert result.chunks and len(sent) == 5


def test_full_text_follows_the_public_lane_unless_switched_off() -> None:
    assert Settings(env="test").fulltext_on is False  # public research is off by default
    assert Settings(env="test", fulltext_enabled=True).fulltext_on is False  # it cannot work without the lane
    assert Settings(env="test", public_research_enabled=True).fulltext_on is True
    assert Settings(env="test", public_research_enabled=True, fulltext_enabled=False).fulltext_on is False


def test_the_pdf_hosts_are_in_the_default_allow_list() -> None:
    assert {"arxiv.org", "europepmc.org"} <= set(Settings(env="test").egress_allow_host_list)


def test_a_paper_found_with_an_open_access_hint_keeps_it() -> None:
    paper = Paper(
        source="openalex", title="T", text=ABSTRACT, url="https://doi.org/10.1/x", oa_url="https://arxiv.org/pdf/1"
    )
    assert paper.oa_url == "https://arxiv.org/pdf/1" and paper.key.startswith("title:")


def test_a_blank_flag_in_the_environment_means_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FULLTEXT_ENABLED", "")  # what docker compose passes for `FULLTEXT_ENABLED: ${FULLTEXT_ENABLED:-}`
    monkeypatch.setenv("PUBLIC_RESEARCH_ENABLED", "true")
    assert Settings(_env_file=None).fulltext_enabled is None  # type: ignore[call-arg]
    assert Settings(_env_file=None).fulltext_on is True  # type: ignore[call-arg]
    monkeypatch.setenv("FULLTEXT_ENABLED", "false")
    assert Settings(_env_file=None).fulltext_on is False  # type: ignore[call-arg]
