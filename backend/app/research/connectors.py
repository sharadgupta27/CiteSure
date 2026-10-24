"""Scholarly search APIs. Free, keyless, and each returns abstracts we can quote.

Every connector does two separate things: build a request (query in, URL and params out) and parse a response
(bytes in, `Paper`s out). The parsers are pure functions so tests can feed them recorded payloads. Only `fetch`
touches the network, and only through the EgressClient.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Protocol
from urllib.parse import quote

from bs4 import BeautifulSoup

from app.egress import EgressClient
from app.research.papers import Paper

ATOM = {"a": "http://www.w3.org/2005/Atom"}
MIN_ABSTRACT_CHARS = 80  # shorter than this is a title or a stub, not evidence


class Connector(Protocol):
    name: str

    async def search(self, client: EgressClient, query: str, limit: int) -> list[Paper]: ...


def _strip_markup(text: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(text or "", "html.parser").get_text(" ")).strip()


def _terms(query: str, limit: int = 6) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", query)[:limit]


def _year(value: Any) -> int | None:
    try:
        year = int(str(value)[:4])
    except (TypeError, ValueError):
        return None
    return year if 1000 < year < 3000 else None


def _keep(papers: list[Paper]) -> list[Paper]:
    return [p for p in papers if p.title and len(p.text) >= MIN_ABSTRACT_CHARS]


# --- arXiv ---------------------------------------------------------------------------------------------------------
def _atom_root(content: bytes) -> ET.Element:
    head = content[:2048].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in content[:8192].upper():
        raise ValueError("DTD in an Atom feed")  # arXiv never sends one; refusing it removes the entity-expansion risk
    return ET.fromstring(content)  # noqa: S314


def parse_arxiv(content: bytes) -> list[Paper]:
    root = _atom_root(content)
    papers: list[Paper] = []
    for entry in root.findall("a:entry", ATOM):
        link = entry.findtext("a:id", default="", namespaces=ATOM).strip()
        papers.append(
            Paper(
                source="arxiv",
                title=_strip_markup(entry.findtext("a:title", default="", namespaces=ATOM)),
                text=_strip_markup(entry.findtext("a:summary", default="", namespaces=ATOM)),
                url=link.replace("http://", "https://", 1),
                authors=tuple(a.findtext("a:name", default="", namespaces=ATOM) for a in entry.findall("a:author", ATOM)),
                year=_year(entry.findtext("a:published", default="", namespaces=ATOM)),
            )
        )
    return _keep(papers)


class ArxivConnector:
    name = "arxiv"

    async def search(self, client: EgressClient, query: str, limit: int) -> list[Paper]:
        terms = _terms(query, 4)
        if not terms:
            return []
        params = {"search_query": " AND ".join(f"all:{t}" for t in terms), "max_results": str(limit), "sortBy": "relevance"}
        response = await client.get(self.name, "https://export.arxiv.org/api/query", params=params, fingerprint_of=query)
        return parse_arxiv(response.content) if response.status == 200 else []


# --- Crossref ------------------------------------------------------------------------------------------------------
def parse_crossref(content: bytes) -> list[Paper]:
    items = json.loads(content).get("message", {}).get("items", [])
    papers: list[Paper] = []
    for item in items:
        authors = tuple(" ".join(part for part in (a.get("given"), a.get("family")) if part) for a in item.get("author", []))
        issued = (item.get("issued", {}).get("date-parts") or [[None]])[0]
        doi = item.get("DOI")
        papers.append(
            Paper(
                source="crossref",
                title=_strip_markup((item.get("title") or [""])[0]),
                text=_strip_markup(item.get("abstract", "")),
                url=item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
                authors=authors,
                year=_year(issued[0] if issued else None),
                doi=doi,
            )
        )
    return _keep([p for p in papers if p.url])


class CrossrefConnector:
    name = "crossref"

    def __init__(self, contact_email: str = "") -> None:
        self._mailto = contact_email

    async def search(self, client: EgressClient, query: str, limit: int) -> list[Paper]:
        params = {
            "query.bibliographic": query,
            "rows": str(limit),
            "filter": "has-abstract:true",
            "select": "DOI,title,abstract,author,issued,URL",
        }
        if self._mailto:
            params["mailto"] = self._mailto
        response = await client.get(self.name, "https://api.crossref.org/works", params=params, fingerprint_of=query)
        return parse_crossref(response.content) if response.status == 200 else []


# --- OpenAlex ------------------------------------------------------------------------------------------------------
def rebuild_abstract(inverted: dict[str, list[int]] | None) -> str:
    """OpenAlex ships abstracts as {word: [positions]} (a copyright workaround). Put the words back in order."""
    if not inverted:
        return ""
    positions: dict[int, str] = {}
    for word, places in inverted.items():
        for place in places:
            positions[place] = word
    return " ".join(positions[i] for i in sorted(positions))


def parse_openalex(content: bytes) -> list[Paper]:
    papers: list[Paper] = []
    for work in json.loads(content).get("results", []):
        doi = work.get("doi")
        landing = ((work.get("primary_location") or {}).get("landing_page_url")) or doi or work.get("id", "")
        papers.append(
            Paper(
                source="openalex",
                title=_strip_markup(work.get("display_name") or work.get("title") or ""),
                text=rebuild_abstract(work.get("abstract_inverted_index")),
                url=doi or landing,
                authors=tuple((a.get("author") or {}).get("display_name", "") for a in work.get("authorships", [])[:6]),
                year=_year(work.get("publication_year")),
                doi=doi,
            )
        )
    return _keep([p for p in papers if p.url])


class OpenAlexConnector:
    name = "openalex"

    def __init__(self, contact_email: str = "") -> None:
        self._mailto = contact_email

    async def search(self, client: EgressClient, query: str, limit: int) -> list[Paper]:
        params = {
            "search": query,
            "per-page": str(limit),
            "filter": "has_abstract:true",
            "select": "id,doi,display_name,publication_year,authorships,abstract_inverted_index,primary_location",
        }
        if self._mailto:
            params["mailto"] = self._mailto
        response = await client.get(self.name, "https://api.openalex.org/works", params=params, fingerprint_of=query)
        return parse_openalex(response.content) if response.status == 200 else []


# --- Europe PMC (includes PubMed) ----------------------------------------------------------------------------------
def _europepmc_url(record: dict[str, Any]) -> str:
    return f"https://europepmc.org/article/{quote(str(record.get('source', 'MED')))}/{quote(str(record.get('id', '')))}"


def parse_europepmc(content: bytes) -> list[Paper]:
    papers: list[Paper] = []
    for record in json.loads(content).get("resultList", {}).get("result", []):
        doi = record.get("doi")
        papers.append(
            Paper(
                source="europepmc",
                title=_strip_markup(record.get("title", "")),
                text=_strip_markup(record.get("abstractText", "")),
                url=_europepmc_url(record),
                authors=tuple(a.strip() for a in (record.get("authorString") or "").rstrip(".").split(",") if a.strip()),
                year=_year(record.get("pubYear")),
                doi=doi,
            )
        )
    return _keep([p for p in papers if not p.url.endswith("/")])


class EuropePmcConnector:
    name = "europepmc"

    async def search(self, client: EgressClient, query: str, limit: int) -> list[Paper]:
        terms = _terms(query, 6)
        if not terms:
            return []
        params = {
            "query": "(" + " AND ".join(terms) + ") AND HAS_ABSTRACT:y",
            "format": "json",
            "resultType": "core",
            "pageSize": str(limit),
        }
        response = await client.get(
            self.name, "https://www.ebi.ac.uk/europepmc/webservices/rest/search", params=params, fingerprint_of=query
        )
        return parse_europepmc(response.content) if response.status == 200 else []


# --- Semantic Scholar (optional: unauthenticated use is rate limited) -----------------------------------------------
def parse_semantic_scholar(content: bytes) -> list[Paper]:
    papers: list[Paper] = []
    for record in json.loads(content).get("data", []):
        doi = (record.get("externalIds") or {}).get("DOI")
        papers.append(
            Paper(
                source="semanticscholar",
                title=_strip_markup(record.get("title", "")),
                text=_strip_markup(record.get("abstract") or ""),
                url=record.get("url") or (f"https://doi.org/{doi}" if doi else ""),
                authors=tuple(a.get("name", "") for a in record.get("authors", [])[:6]),
                year=_year(record.get("year")),
                doi=doi,
            )
        )
    return _keep([p for p in papers if p.url])


class SemanticScholarConnector:
    name = "semanticscholar"

    async def search(self, client: EgressClient, query: str, limit: int) -> list[Paper]:
        params = {"query": query, "limit": str(limit), "fields": "title,abstract,year,authors,url,externalIds"}
        response = await client.get(
            self.name, "https://api.semanticscholar.org/graph/v1/paper/search", params=params, fingerprint_of=query
        )
        return parse_semantic_scholar(response.content) if response.status == 200 else []


SCHOLARLY = {"arxiv", "crossref", "openalex", "europepmc", "semanticscholar"}


def build_connectors(names: list[str], contact_email: str = "") -> list[Connector]:
    available: dict[str, Connector] = {
        "arxiv": ArxivConnector(),
        "crossref": CrossrefConnector(contact_email),
        "openalex": OpenAlexConnector(contact_email),
        "europepmc": EuropePmcConnector(),
        "semanticscholar": SemanticScholarConnector(),
    }
    unknown = [n for n in names if n not in available and n != "web"]
    if unknown:
        raise RuntimeError(f"Unknown PUBLIC_SOURCES entries: {', '.join(unknown)}")
    return [available[n] for n in names if n in available]
