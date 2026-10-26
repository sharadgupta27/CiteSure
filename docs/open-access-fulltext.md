# Open-access full text of published papers

Public search returns **abstracts**. When a paper is open access, a user can add its full text on demand, and later questions can cite page-numbered passages from it instead of only the abstract. The text is public, stays in its own tables, and never mixes with company documents.

## How it works

```text
"Fetch full text" ─▶ POST /research/fulltext ─▶ identify paper ─▶ budget check ─▶ job queued
                                                                                     │ (worker)
 egress guard ◀─ identifier ◀─ find an open-access PDF ◀─ OpenAlex / Semantic Scholar / Europe PMC / arXiv
      │
      └─▶ EgressClient (allow-list, https, SSRF + redirect checks, byte cap, time limit)
              └─▶ %PDF- + content-type check ─▶ page cap ─▶ parse_pdf ─▶ chunker ─▶ embedder ─▶ fulltext_* tables
```

1. **Identify.** The request carries a citation address or DOI. Only addresses that name a paper by a public identifier are accepted: `doi.org`, `arxiv.org`, `europepmc.org/article/...`, `openalex.org/W...`, or an explicit DOI. An arbitrary web page is refused (`422`). The server derives the paper's identity itself; the client cannot attach a PDF to another paper.
2. **Budget.** Each workspace has `FULLTEXT_DAILY_FETCHES` downloads per UTC day (default 20). A paper already in the cache is returned at once and costs nothing; a second click on a request in flight shares it. Over budget the reply is `429` with code `fulltext_budget_exceeded` and a plain message. Failed lookups still count when something was contacted; a request the guard stopped counts nothing.
3. **Find.** The worker asks the sources enabled in `PUBLIC_SOURCES` for an open-access location, in order: arXiv (its own PDF), OpenAlex (`best_oa_location`, `open_access.oa_url`, other open locations), Semantic Scholar (`openAccessPdf`), Europe PMC (open-access full-text links, or the PMC render service). Up to four candidate addresses are tried; a landing page that is not a PDF just moves on to the next. Search results also carry the hint as `Paper.oa_url`.
4. **Fetch.** Only through `EgressClient`. A candidate on a host outside `EGRESS_ALLOW_HOSTS` is not contacted and is reported as `host_not_allowed` (with `EGRESS_MODE=open` any public https host is allowed, private and loopback addresses never are). Redirects are re-validated hop by hop. The response must be at most `FULLTEXT_MAX_BYTES` (checked from `Content-Length` and again while streaming), arrive within `FULLTEXT_TIMEOUT_S`, have a PDF-compatible content type and start with `%PDF-`.
5. **Parse and index.** The page count is read first (`FULLTEXT_MAX_PAGES`, default 150); then `parse_pdf` runs in a thread with `FULLTEXT_PARSE_TIMEOUT_S`; the chunker keeps page numbers and offsets; more than `FULLTEXT_MAX_CHUNKS` passages is refused. Passages are embedded with the configured embedder and stored with a tsvector for keyword search.
6. **Cache.** Papers are kept `FULLTEXT_CACHE_TTL_DAYS` (default 30); an expired paper is ignored by questions and replaced on the next request. The cache is shared by workspaces (it is public text, and the budget is what limits spending).

## What leaves the system

Only a **public paper identifier** (a DOI, an arXiv id, a Europe PMC id, an OpenAlex id) and the PDF address that a public API reported. No question text, document text, workspace or user id. Because a DOI field is free text, every identifier still passes the egress guard first: personal data, secrets, deny terms, canaries, and a run of words copied from a stored document block the request before anything is sent (digit runs that look like phone numbers, common in DOIs, are the one exemption). A blocked request shows reason codes, never the text.

The request records what happened, and the UI shows it: one entry per destination host with `sent`, `blocked` or `failed`, and the identifier that was sent. These records are on the request (`GET /research/fulltext/{id}`), not on later answers, because the download happens when the user clicks, not when they ask. Answers stay truthful too: looking up the cache sends nothing, so it adds no egress entry, and the search of public sources is disclosed exactly as before.

## Isolation

| Concern | How it is kept |
|---|---|
| Not in the internal corpus | separate tables `fulltext_papers`, `fulltext_chunks` (migration 0003); `chunks`/`documents` are never written |
| Never returned by internal retrieval | internal queries read `chunks` only; the cache is read only by the public lane (`rag/retrieval/fulltext.py`), for scope `public` or `both` |
| No ACL space | passages carry `source_type="public"` and the public collection id; `/chunks/{id}` answers 404 for them |
| Private mode unchanged | company text still goes only to the internal model; a hosted model reads these passages like any public text; the worker reaches the internet only through the egress proxy |
| Verification unchanged | passages are real text, so quote matching and entailment run as for any source; a cited passage shows its page numbers |

## Hosts

`arxiv.org` and `europepmc.org` were added to `EGRESS_ALLOW_HOSTS` and `deploy/egress/allowlist.txt` (a test keeps them equal). Many open-access PDFs live on publisher or repository hosts; those are skipped with the message that the host is not allowed. Add a host to both lists to allow it. Unpaywall was not added: OpenAlex already carries its open-access data.

## API

| Operation | Purpose |
|---|---|
| `POST /research/fulltext` (`requestFullText`) | `{workspace_id, url, doi?}` returns `queued`, or `ready` at once when cached. 422 feature off or no paper, 429 rate limit or budget, 404 not a member |
| `GET /research/fulltext/{request_id}` (`getFullTextStatus`) | `queued`, `running`, `ready` or `failed`, with `passages`, `pages`, `error` code, `message`, `fetches_remaining`, `egress`. Only the requester can read it |

Error codes: `unsupported_source`, `no_open_access`, `host_not_allowed`, `not_pdf`, `too_large`, `too_long`, `unreadable` (scanned, encrypted or damaged), `timeout`, `fetch_failed`, `blocked`, `disabled`, `internal_error`. The worker handles the job (`fulltext_fetch`); nothing is retried, since a retry would download again.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `FULLTEXT_ENABLED` | empty | empty follows `PUBLIC_RESEARCH_ENABLED`; `false` turns only this feature off; it never works without the public lane |
| `FULLTEXT_DAILY_FETCHES` | `20` | downloads per workspace per UTC day; `0` refuses all new downloads |
| `FULLTEXT_MAX_BYTES` | `25000000` | largest PDF for one paper |
| `FULLTEXT_MAX_PAGES` | `150` | longer PDFs are refused before parsing |
| `FULLTEXT_MAX_CHUNKS` | `800` | bounds embedding work |
| `FULLTEXT_CACHE_TTL_DAYS` | `30` | cache lifetime |
| `FULLTEXT_TIMEOUT_S`, `FULLTEXT_PARSE_TIMEOUT_S` | `60`, `60` | download and parse time limits |

## Limits

- Scanned PDFs have no text; they fail as `unreadable` until OCR (phase 5) is available.
- Only open-access copies on allow-listed hosts are fetched; the abstract remains the fallback.
- A parse cannot be killed once started: the byte and page caps come first, and the worker is a separate process.
- Retrieval over the cache needs a keyword match with the question (a gate against unrelated passages), then ranks by keyword and vector together; the existing reranker orders the final list.
- Respect each publisher's terms; passages are quoted for citation, like abstracts.

## Proof

`tests/unit/test_fulltext.py` (identification, source parsing, every fetch refusal, finder fallbacks, parse caps, cache in the lane) and `tests/integration/test_fulltext.py` (worker flow with page-numbered citations, isolation from `chunks`, cache hits, budget, guard blocks in private mode, expiry, failure of the cache lookup).
