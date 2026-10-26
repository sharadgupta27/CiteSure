"""Open-access full text against a real database and a scripted internet: request, budget, worker, cache, retrieval.

The assertions that matter: the PDF came only through the egress client and an allow-listed host, the text lives in the
public cache and nowhere in the internal corpus, a cited passage carries its page number, and each failure is a clear
error that costs only what it actually used."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.config import Settings
from app.egress.client import EgressClient
from app.llm.fake import FakeProvider
from app.research.connectors import build_connectors
from app.research.service import ResearchKit
from tests.conftest import ingest_all, new_workspace, register
from tests.unit.test_fulltext import paper_pdf
from tests.unit.test_research import mock_network

API = "/api/v1"
QUESTION = "How does block sparse attention reduce memory use?"
SENTENCE = "Block sparse attention reduces memory use by forty percent."


@dataclass
class Net:
    """The scripted internet. `pdf_hosts` maps a PDF host to its reply; every request is recorded."""

    sent: list[httpx.Request] = field(default_factory=list)
    open_access: dict[str, str] = field(default_factory=dict)  # doi -> pdf address OpenAlex reports
    pdf: bytes = field(default_factory=paper_pdf)

    def handler(self, search: Callable[[httpx.Request], httpx.Response]) -> Callable[[httpx.Request], httpx.Response]:
        def handle(request: httpx.Request) -> httpx.Response:
            host, path = request.url.host, request.url.path
            if host == "api.openalex.org" and path.startswith("/works/doi:"):
                self.sent.append(request)
                doi = path.removeprefix("/works/doi:")
                work: dict[str, Any] = {
                    "id": "https://openalex.org/W1",
                    "doi": f"https://doi.org/{doi}",
                    "display_name": "Block sparse attention, revisited",
                    "publication_year": 2023,
                    "authorships": [{"author": {"display_name": "Grace Hopper"}}],
                }
                if doi in self.open_access:
                    work["best_oa_location"] = {"pdf_url": self.open_access[doi]}
                return httpx.Response(200, content=json.dumps(work).encode())
            if host in ("api.semanticscholar.org", "www.ebi.ac.uk") and (
                "/paper/DOI:" in path or request.url.params.get("query", "").startswith(("DOI:", "EXT_ID:"))
            ):
                self.sent.append(request)
                return httpx.Response(
                    404 if host == "api.semanticscholar.org" else 200, content=b'{"resultList":{"result":[]}}'
                )
            if host == "arxiv.org" and path.startswith("/pdf/"):
                self.sent.append(request)
                return httpx.Response(200, content=self.pdf, headers={"content-type": "application/pdf"})
            return search(request)

        return handle

    def pdf_requests(self) -> list[httpx.Request]:
        return [r for r in self.sent if r.url.host == "arxiv.org"]


@dataclass
class World:
    workspace_id: str
    admin: dict[str, str]
    net: Net
    search_sent: list[httpx.Request]

    def doi(self) -> str:
        return f"10.1000/ft-{uuid.uuid4().hex[:10]}"

    def serve(self, doi: str, address: str | None = None) -> str:
        """Make `doi` open access at a (default arXiv) address and return the DOI-resolver URL a citation would carry."""
        self.net.open_access[doi] = address or f"https://arxiv.org/pdf/{uuid.uuid4().hex[:8]}"
        return f"https://doi.org/{doi}"


@pytest.fixture
async def world(app: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[World]:
    workspace_id, admin, _ = await new_workspace(client)
    settings = Settings(env="test", public_research_enabled=True, public_llm_provider="fake")
    search_sent: list[httpx.Request] = []
    net = Net()
    http = EgressClient(
        mode="allowlist",
        allow_hosts=settings.egress_allow_host_list,
        user_agent="t",
        timeout_s=5,
        max_bytes=500_000,
        check_dns=False,
        transport=httpx.MockTransport(net.handler(mock_network(search_sent).handler)),  # type: ignore[attr-defined]
    )
    providers = app.state.providers
    monkeypatch.setattr(providers, "research", ResearchKit(settings, http, build_connectors(settings.public_source_list)))
    monkeypatch.setattr(providers, "public_llm", FakeProvider())
    for name, value in {"public_research_enabled": True, "fulltext_daily_fetches": 20, "fulltext_enabled": None}.items():
        monkeypatch.setattr(app.state.settings, name, value)
    yield World(workspace_id, admin, net, search_sent)
    async with app.state.sessionmaker() as session:  # the cache is global: leave none of it for the next test
        await session.execute(text("DELETE FROM fulltext_papers"))
        await session.commit()


async def request_full_text(client: httpx.AsyncClient, world: World, url: str, **extra: Any) -> httpx.Response:
    return await client.post(
        f"{API}/research/fulltext", json={"workspace_id": world.workspace_id, "url": url, **extra}, headers=world.admin
    )


async def status_of(client: httpx.AsyncClient, world: World, request_id: str) -> dict[str, Any]:
    response = await client.get(f"{API}/research/fulltext/{request_id}", headers=world.admin)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def add_paper(app: Any, client: httpx.AsyncClient, world: World) -> tuple[str, dict[str, Any]]:
    url = world.serve(world.doi())
    queued = await request_full_text(client, world, url)
    assert queued.status_code == 200, queued.text
    await ingest_all(app)
    return url, await status_of(client, world, queued.json()["id"])


async def test_a_paper_is_fetched_by_the_worker_and_cited_with_page_numbers(
    app: Any, client: httpx.AsyncClient, world: World
) -> None:
    url = world.serve(world.doi())
    queued = await request_full_text(client, world, url)
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued" and queued.json()["fetches_remaining"] == 19  # reserved at request time
    assert world.net.sent == []  # nothing happens in the request handler: the worker downloads

    await ingest_all(app)
    done = await status_of(client, world, queued.json()["id"])
    assert done["status"] == "ready" and done["error"] is None and done["cached"] is False
    assert done["passages"] >= 1 and done["pages"] == 2 and done["title"].startswith("Block sparse attention, revisited")
    assert {r["destination"] for r in done["egress"]} == {"api.openalex.org", "arxiv.org"}
    assert all(r["status"] == "sent" for r in done["egress"])

    # Only a public DOI and an arXiv address went out: no question text, no workspace id.
    wire = "\n".join(str(r.url) for r in world.net.sent)
    assert wire.count("doi:") == 1 and QUESTION.lower() not in wire.lower() and world.workspace_id not in wire

    answer = (
        await client.post(
            f"{API}/ask",
            json={"workspace_id": world.workspace_id, "question": QUESTION, "scope": "public"},
            headers=world.admin,
        )
    ).json()
    cited = [c for claim in answer["claims"] for c in claim["citations"]]
    full_text = [c for c in cited if c["page_start"] is not None]
    assert answer["status"] == "answered" and full_text, answer
    assert full_text[0]["source_type"] == "public" and full_text[0]["url"] == url
    assert "forty percent" in full_text[0]["quote"] and full_text[0]["page_start"] in (1, 2)
    assert full_text[0]["document_title"].startswith("Block sparse attention, revisited (Hopper, 2023)")
    assert len(world.search_sent) == 5  # the usual search still ran; the cache added no request


async def test_full_text_never_enters_the_internal_corpus(app: Any, client: httpx.AsyncClient, world: World) -> None:
    _, done = await add_paper(app, client, world)
    assert done["status"] == "ready"

    async with app.state.sessionmaker() as session:
        in_chunks = (
            await session.execute(text("SELECT count(*) FROM chunks WHERE text ILIKE '%forty percent%'"))
        ).scalar_one()
        stored = (
            await session.execute(text("SELECT count(*) FROM fulltext_chunks WHERE text ILIKE '%forty percent%'"))
        ).scalar_one()
        fulltext_id = (await session.execute(text("SELECT id FROM fulltext_chunks LIMIT 1"))).scalar_one()
    assert in_chunks == 0 and stored >= 1

    internal = (
        await client.post(
            f"{API}/ask",
            json={"workspace_id": world.workspace_id, "question": QUESTION, "scope": "internal"},
            headers=world.admin,
        )
    ).json()
    assert all(c["source_type"] == "internal" for claim in internal["claims"] for c in claim["citations"])
    assert "forty percent" not in json.dumps(internal)
    assert (await client.get(f"{API}/chunks/{fulltext_id}", headers=world.admin)).status_code == 404
    explain = await client.get(
        f"{API}/retrieval/explain", params={"workspace_id": world.workspace_id, "query": QUESTION}, headers=world.admin
    )
    assert explain.status_code == 200 and "forty percent" not in explain.text


async def test_a_cached_paper_is_ready_at_once_costs_nothing_and_downloads_nothing(
    app: Any, client: httpx.AsyncClient, world: World
) -> None:
    url, first = await add_paper(app, client, world)
    downloads = len(world.net.pdf_requests())
    again = await request_full_text(client, world, url)
    body = again.json()
    assert body["status"] == "ready" and body["cached"] is True and body["passages"] == first["passages"]
    assert body["egress"] == [] and body["fetches_remaining"] == first["fetches_remaining"]
    assert len(world.net.pdf_requests()) == downloads == 1

    other = await register(client, "other")
    mine = await client.get(f"{API}/research/fulltext/{body['id']}", headers=other[1])
    assert mine.status_code == 404  # someone else's request


async def test_an_in_flight_request_is_shared_not_charged_twice(client: httpx.AsyncClient, world: World) -> None:
    url = world.serve(world.doi())
    first = (await request_full_text(client, world, url)).json()
    second = (await request_full_text(client, world, url)).json()
    assert second["id"] == first["id"] and second["fetches_remaining"] == 19


async def test_the_daily_budget_stops_new_downloads_with_a_clear_error(
    app: Any, client: httpx.AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.state.settings, "fulltext_daily_fetches", 2)
    for _ in range(2):
        assert (await request_full_text(client, world, world.serve(world.doi()))).status_code == 200
    over = await request_full_text(client, world, world.serve(world.doi()))
    assert over.status_code == 429 and over.json()["code"] == "fulltext_budget_exceeded"
    assert "2 open-access downloads for today" in over.json()["detail"]

    await ingest_all(app)  # the two accepted requests still complete
    other_workspace = await new_workspace(client)
    elsewhere = await client.post(
        f"{API}/research/fulltext",
        json={"workspace_id": other_workspace[0], "url": world.serve(world.doi())},
        headers=other_workspace[1],
    )
    assert elsewhere.status_code == 200  # the budget is per workspace


async def test_a_budget_of_zero_refuses_every_new_download_but_serves_the_cache(
    app: Any, client: httpx.AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, _ = await add_paper(app, client, world)
    monkeypatch.setattr(app.state.settings, "fulltext_daily_fetches", 0)
    assert (await request_full_text(client, world, world.serve(world.doi()))).status_code == 429
    assert (await request_full_text(client, world, url)).json()["status"] == "ready"


async def test_no_open_access_copy_is_a_clear_failure_that_still_counts_the_lookups(
    app: Any, client: httpx.AsyncClient, world: World
) -> None:
    queued = await request_full_text(client, world, f"https://doi.org/{world.doi()}")  # not served: no OA location
    await ingest_all(app)
    done = await status_of(client, world, queued.json()["id"])
    assert done["status"] == "failed" and done["error"] == "no_open_access"
    assert "No open-access PDF" in done["message"]
    assert done["fetches_remaining"] == 19 and world.net.pdf_requests() == []


async def test_a_copy_on_a_host_that_is_not_allow_listed_is_never_contacted(
    app: Any, client: httpx.AsyncClient, world: World
) -> None:
    queued = await request_full_text(client, world, world.serve(world.doi(), "https://publisher.example/paper.pdf"))
    await ingest_all(app)
    done = await status_of(client, world, queued.json()["id"])
    assert done["status"] == "failed" and done["error"] == "host_not_allowed"
    assert any(
        r["destination"] == "publisher.example" and r["status"] == "blocked" and r["query"] is None for r in done["egress"]
    )
    assert "publisher.example" not in {r.url.host for r in world.net.sent}


async def test_a_page_that_is_not_a_pdf_is_a_clear_failure(app: Any, client: httpx.AsyncClient, world: World) -> None:
    world.net.pdf = b"<html>Please log in</html>"
    queued = await request_full_text(client, world, world.serve(world.doi()))
    await ingest_all(app)
    done = await status_of(client, world, queued.json()["id"])
    assert done["status"] == "failed" and done["error"] in ("no_open_access", "not_pdf")
    async with app.state.sessionmaker() as session:
        assert (await session.execute(text("SELECT count(*) FROM fulltext_papers"))).scalar_one() == 0


async def test_an_oversized_pdf_is_refused_by_the_byte_cap(
    app: Any, client: httpx.AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.state.settings, "fulltext_max_bytes", 100_000)
    world.net.pdf = b"%PDF-1.7\n" + b"0" * 150_000
    queued = await request_full_text(client, world, world.serve(world.doi()))
    await ingest_all(app)
    done = await status_of(client, world, queued.json()["id"])
    assert done["status"] == "failed" and done["error"] == "too_large"


async def test_an_identifier_the_egress_guard_dislikes_is_not_sent_and_is_not_charged(
    app: Any, client: httpx.AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.state.settings, "egress_deny_terms", "Phoenix")
    queued = await request_full_text(client, world, "https://doi.org/10.1000/phoenix-budget-2027")
    await ingest_all(app)
    done = await status_of(client, world, queued.json()["id"])
    assert done["status"] == "failed" and done["error"] == "blocked"
    assert [r["status"] for r in done["egress"]] == ["blocked"] and done["egress"][0]["query"] is None
    assert "Phoenix" not in json.dumps(done) and "phoenix" not in done["egress"][0]["reason"]
    assert world.net.sent == [] and done["fetches_remaining"] == 20  # nothing left, nothing charged


async def test_requests_that_name_no_paper_or_come_from_outsiders_are_refused(
    client: httpx.AsyncClient, world: World
) -> None:
    web = await request_full_text(client, world, "https://example.com/blog/post")
    assert web.status_code == 422 and web.json()["code"] == "invalid_input"
    other_ws = await new_workspace(client)
    stranger = await client.post(
        f"{API}/research/fulltext",
        json={"workspace_id": world.workspace_id, "url": "https://doi.org/10.1000/abc"},
        headers=other_ws[1],
    )
    assert stranger.status_code == 404  # not a member of that workspace
    anonymous = await client.post(
        f"{API}/research/fulltext", json={"workspace_id": world.workspace_id, "url": "https://doi.org/10.1/x"}
    )
    assert anonymous.status_code == 401
    assert (await client.get(f"{API}/research/fulltext/{uuid.uuid4()}", headers=world.admin)).status_code == 404
    assert world.net.sent == []


async def test_the_feature_can_be_switched_off(
    app: Any, client: httpx.AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.state.settings, "fulltext_enabled", False)
    off = await request_full_text(client, world, world.serve(world.doi()))
    assert off.status_code == 422 and "not turned on" in off.json()["detail"]
    monkeypatch.setattr(app.state.settings, "fulltext_enabled", None)
    monkeypatch.setattr(app.state.settings, "public_research_enabled", False)
    assert (await request_full_text(client, world, world.serve(world.doi()))).status_code == 422


async def test_an_expired_paper_is_ignored_by_questions_and_fetched_afresh(
    app: Any, client: httpx.AsyncClient, world: World
) -> None:
    url, _ = await add_paper(app, client, world)
    async with app.state.sessionmaker() as session:
        await session.execute(text("UPDATE fulltext_papers SET expires_at = now() - interval '1 day'"))
        await session.commit()
    answer = (
        await client.post(
            f"{API}/ask",
            json={"workspace_id": world.workspace_id, "question": QUESTION, "scope": "public"},
            headers=world.admin,
        )
    ).json()
    assert all(c["page_start"] is None for claim in answer["claims"] for c in claim["citations"])

    again = await request_full_text(client, world, url)
    assert again.json()["status"] == "queued"  # the stale copy does not count as cached
    await ingest_all(app)
    assert (await status_of(client, world, again.json()["id"]))["status"] == "ready"
    assert len(world.net.pdf_requests()) == 2


async def test_a_database_failure_in_the_cache_lookup_does_not_break_the_answer(
    app: Any, client: httpx.AsyncClient, world: World
) -> None:
    async with app.state.sessionmaker() as session:  # simulate a deployment where migration 0003 has not run
        await session.execute(text("ALTER TABLE fulltext_chunks RENAME TO fulltext_chunks_gone"))
        await session.commit()
    try:
        response = await client.post(
            f"{API}/ask",
            json={"workspace_id": world.workspace_id, "question": QUESTION, "scope": "public"},
            headers=world.admin,
        )
        assert response.status_code == 200 and response.json()["status"] == "answered"
    finally:
        async with app.state.sessionmaker() as session:
            await session.execute(text("ALTER TABLE fulltext_chunks_gone RENAME TO fulltext_chunks"))
            await session.commit()


CANARY = "CANARY-9c1d-INTERNAL"
INTERNAL_SENTENCE = "The retention formula multiplies weekly active seats by the churn coefficient every quarter."


async def test_company_text_cannot_ride_along_in_an_identifier_in_private_mode(
    app: Any, client: httpx.AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.egress.corpus import reset_name_cache

    workspace_id, admin, collection_id = await new_workspace(client)
    document = f"# Notes\n\n{INTERNAL_SENTENCE}\n\nMarker {CANARY} stays inside.\n"
    uploaded = await client.post(
        f"{API}/collections/{collection_id}/documents",
        files={"file": ("notes.md", document.encode(), "text/markdown")},
        headers=admin,
    )
    assert uploaded.status_code == 202
    await ingest_all(app)
    reset_name_cache()
    monkeypatch.setattr(app.state.settings, "private_mode", True)
    monkeypatch.setattr(app.state.settings, "egress_canaries", CANARY)

    async def attempt(url: str) -> dict[str, Any]:
        queued = await client.post(
            f"{API}/research/fulltext", json={"workspace_id": workspace_id, "url": url}, headers=admin
        )
        assert queued.status_code == 200, queued.text
        await ingest_all(app)
        done = await client.get(f"{API}/research/fulltext/{queued.json()['id']}", headers=admin)
        body: dict[str, Any] = done.json()
        return body

    smuggled = [
        "https://doi.org/10.1000/the-retention-formula-multiplies-weekly-active-seats",  # six words of a document
        f"https://doi.org/10.1000/{CANARY.lower()}",  # a planted marker
    ]
    for url in smuggled:
        done = await attempt(url)
        assert done["status"] == "failed" and done["error"] == "blocked", done
        assert done["egress"][0]["status"] == "blocked" and done["egress"][0]["query"] is None
        assert "retention" not in json.dumps(done).lower() and CANARY.lower() not in json.dumps(done).lower()
    assert world.net.sent == []  # not one request left the process

    fine = await attempt(world.serve(world.doi()))  # an ordinary paper still goes through in private mode
    assert fine["status"] == "ready"
    wire = "\n".join(str(r.url) for r in world.net.sent).lower()
    assert CANARY.lower() not in wire and "retention" not in wire and "churn" not in wire
