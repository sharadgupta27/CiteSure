# Public research: published papers and web pages, without letting company text out

CiteSure answers from two kinds of sources and keeps them apart.

| Lane | Reads | Answered by | Network |
|---|---|---|---|
| **Internal** | the collections the asker may read | a model on this machine or private network (`LLM_PROVIDER=local`) | none |
| **Public** | published papers, preprints, web pages | the same local model, or Claude when no company text is involved | only through the egress guard and the allow-list proxy |

The asker chooses a **scope** per question: `internal` (default), `public`, or `both`. The API takes `scope` on `POST /ask` and `/ask/stream`; the UI shows a selector whenever the server has the public lane on.

## What is sent where

```text
question ──▶ egress guard ──▶ keyword query ──▶ egress guard ──▶ EgressClient ──▶ proxy ──▶ arXiv, Crossref, OpenAlex,
             (whole question)   (single words)    (the query)      (allow-list)    (allow-list)  Europe PMC / PubMed, ...
                  │
                  └─ question cleared? ──▶ may a hosted model read it
```

1. **Keywords, not sentences.** `research/query.py` keeps at most 8 informative single words, in order. No sentence of the question survives, and a pasted paragraph of a document is reduced to a handful of words.
2. **The guard checks twice**: the whole question and the query (`egress/guard.py`). A block never echoes the blocked text. The server logs and metrics carry precise reason codes (`pii:email`, `deny_term`, `copied_from_documents`...); the **response shows a vaguer one** for anything derived from your documents or lists (`company_content`), because "this sentence exists in a document" is itself information a user could use to probe collections they may not read.
3. **The user can see and edit the query first**: `POST /public-research/preview` returns the exact query and the verdict without sending anything; the edited query goes back as `public_query` on `/ask` and is checked again.
4. **Every answer says what left**: `egress` lists each destination with the query it received, or the reason nothing was sent (`blocked`), or `failed`. The UI shows it under the answer, and the record is stored with the answer.

### What the guard blocks

| Check | Example | Reason code |
|---|---|---|
| Personal data (the ingestion scanner's rules) | an email address, phone number, SSN, IBAN, card number | `pii:*` |
| Credentials | `sk-...` keys, AWS keys, JWTs, private keys, GitHub/Slack tokens, long hex strings | `secret:*` |
| Internal addresses | `10.x.x.x`, `192.168.x.x`, `db.prod.internal`, `wiki.corp` | `internal_address` |
| Confidentiality markers | "company confidential", "do not distribute" | `confidential_marker` |
| **Never-share list** | `EGRESS_DENY_TERMS`: project code names, customer names | `deny_term` |
| **Canaries** | `EGRESS_CANARIES`: marker strings planted in documents | `canary` |
| **Copied text** | any run of 6 words (`egress_overlap_words`) found in a stored document, checked with Postgres phrase search over every collection | `copied_from_documents` |
| **Internal names** | workspace, collection and document titles (on in private mode; exempt generic ones with `EGRESS_ALLOW_TERMS`) | `internal_name` |
| Length | a query over 300 characters | `too_long` |

The copied-text check is why a user cannot paste a paragraph of a policy into a public question: the paragraph is found in the database before anything leaves.

## Which model reads what

`services/pipeline.py: choose_llm` is the single place that decides, and `ensure_lane_safe` is a second check that fails loudly if the rule is ever broken.

| Situation | Answering and verifying model |
|---|---|
| Any company text in the prompt (`internal` or `both` with internal hits) | the **internal** model (`providers.llm`). In private mode this is local, and a hosted model is refused at boot and again at call time (`PrivacyViolation`). |
| Public passages only, and the whole question was cleared | the **public** model (`PUBLIC_LLM_PROVIDER=anthropic`: Claude), if configured |
| Public passages only, but the question was not cleared (the user supplied a safe query) | the internal model, because the question itself is part of the prompt |

So Claude never sees a company document, a company question that the guard stopped, or the user's internal wording. It reads papers and web pages, plus questions that look like any public question.

## Sources

| Source | What it returns | Key | Notes |
|---|---|---|---|
| `arxiv` | preprint abstracts | none | |
| `crossref` | abstracts of journal articles that have one | none | `CONTACT_EMAIL` puts you in the faster "polite pool" |
| `openalex` | abstracts of scholarly works | none | abstracts are rebuilt from OpenAlex's inverted index |
| `europepmc` | PubMed and open-access life-science abstracts | none | |
| `semanticscholar` | abstracts | none | unauthenticated use is rate limited, off by default |
| `web` | passages from any published page | Anthropic | Claude's `web_search` tool finds URLs from the guarded query; CiteSure fetches the pages itself, so the quoted text is the page's real text |

Papers are cited by title, authors, year and link. A public citation opens a panel with the exact quote and a link to the original; it has no stored document and nothing to download. The same checks apply as for company text: the quote must exist in the passage and a judge must find the claim supported, otherwise the claim is dropped.

### The web source

`PUBLIC_SOURCES=...,web` needs `PUBLIC_LLM_PROVIDER=anthropic` and `EGRESS_MODE=open` (boot refuses anything else). In open mode the proxy and `EgressClient` allow any public HTTPS host but still refuse private, loopback and link-local addresses, credentials in URLs, plain HTTP and redirects to such places. Pages are fetched with a polite `User-Agent` and a size cap; only HTML and PDF are read. Web search is billed by Anthropic per search; `WEB_SEARCH_MAX_USES` bounds it per question.

## Limits you should know

- **Keywords reveal a topic.** "weeks paid parental leave caregivers" tells a public source that someone is interested in parental leave. That is the price of searching at all. Use the preview, put sensitive names on the never-share list, and use `internal` for anything that must not even hint at its subject.
- **The guard is an oracle of limited power.** A block versus a pass reveals that some company document or list matched. Every probe is rate limited like any question (30 per minute per user) and logged, and the response does not say which rule fired, but a determined insider with many guesses could learn that a specific six-word sentence exists. Watch the `EgressBlocksSpike` alert.
- **The guard is only as good as its lists.** An unlisted code name that appears nowhere in a document title or text will pass. Plant canaries in your most sensitive documents and review the `citesure_egress_decisions_total` panel.
- **Scattered keywords are not caught by the copied-text check.** It looks for 6 consecutive words; a query of 8 unrelated words taken from different places in a document passes if none of its 6-word windows exists in the corpus.
- **Public sources can be wrong or hostile.** Page text is wrapped as untrusted data like any document; an instruction inside a paper is not followed (tests: `test_instructions_hidden_in_a_paper_are_not_followed`). A verified citation proves that a source said something, not that it is true.
- **Terms of use.** Abstracts are quoted for citation, the way a reference manager does. Respect each site's terms for the web source and keep the `User-Agent` contact current (`PUBLIC_USER_AGENT`).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PUBLIC_RESEARCH_ENABLED` | `false` | master switch; off means nothing is ever sent and the scope selector is hidden |
| `DEFAULT_SCOPE` | `internal` | scope when a request omits it |
| `PUBLIC_SOURCES` | `arxiv,crossref,openalex,europepmc` | comma list, see above |
| `PUBLIC_LLM_PROVIDER` | `none` | `anthropic` lets Claude answer public-only questions and power the `web` source |
| `EGRESS_MODE` | `allowlist` | `open` only for the `web` source |
| `EGRESS_ALLOW_HOSTS` | the scholarly APIs and `api.anthropic.com` | must match `deploy/egress/allowlist.txt` (a test enforces it) |
| `EGRESS_PROXY_URL` | empty | the allow-list proxy; required in prod private mode |
| `EGRESS_DENY_TERMS`, `EGRESS_ALLOW_TERMS`, `EGRESS_CANARIES` | empty | the lists above |
| `EGRESS_OVERLAP_WORDS`, `EGRESS_MAX_QUERY_CHARS` | `6`, `300` | guard thresholds |

## Proof

- `tests/integration/test_public_research.py`: with a canary planted in a company document, every request to a public source and every prompt a hosted model receives is recorded, and none contains the canary or any company sentence, for all three scopes, for pasted canaries, copied sentences, and a hostile abstract.
- `tests/unit/test_egress_guard.py`, `test_egress_client.py`, `test_research.py`, `test_web_source.py`, `test_local_llm_and_modes.py`, `test_deploy_config.py`.
- `deploy/verify-isolation.sh` against a running stack (see [private-deployment.md](private-deployment.md)).
