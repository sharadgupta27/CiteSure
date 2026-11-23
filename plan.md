# CiteSure - Plan and Status

> What was planned, what was built and what is still open. The product requirements are in [product-spec.md](product-spec.md); the rubric is in [docs/course/final-project-rubric.md](docs/course/final-project-rubric.md). Who built which phase: [agent-team/](agent-team/README.md).
>
> Status: ✅ done · 🟡 partly done · ⬜ not done.

## 1. Goal

A document Q&A system for a company: every sentence in an answer is cited, every citation is checked against its source, and access control is applied inside retrieval so restricted documents can never leak. Two further requirements were added later: **private mode** (company text never leaves the machine) and a **merge** of the features of a second project, `document_explorer`.

## 2. Key design decisions

| Decision | Choice | Why |
|---|---|---|
| Vector store | pgvector in the same Postgres | One database; ACL filters run in the same SQL as the vector search |
| Keyword search | Postgres full-text search (`tsvector` + GIN) | Hybrid search without Elasticsearch; catches policy IDs and acronyms |
| Fusion and rerank | Reciprocal Rank Fusion, then a cross-encoder (top 30 → top 6) | No score normalisation needed; the reranker raised MRR from 0.91 to 0.98 |
| Embeddings | `fastembed` (local ONNX), fake embedder in tests | No API key or cost for the demo and CI |
| Answer format | Structured claims, each with chunk ids and a quoted span | Makes deterministic citation checks possible |
| Verification | 1) the quote must fuzzy-match the chunk (≥ 0.9), 2) an entailment check by a cheaper model | Catches invented quotes cheaply, and real quotes with wrong conclusions |
| Access control | Pre-filter by allowed collection ids inside the retrieval SQL | Post-filtering leaks through scores, counts and timing |
| Background jobs | Postgres jobs table with `SKIP LOCKED` | No Redis to run |
| Contract | `openapi.yaml` is the source of truth; the TypeScript client is generated from it | A drift test fails when the backend disagrees |
| Private mode | Local model for company text; only guarded keywords go to public sources | A hosted model reading company text counts as the data leaving |

Data model and endpoints: [docs/architecture.md](docs/architecture.md) and [openapi.yaml](openapi.yaml). Every RAG decision and the experiment behind it: [docs/rag-design.md](docs/rag-design.md).

## 3. Phases

| # | Phase | Status | Notes |
|---|---|---|---|
| 0 | Spec, demo corpus, 40 golden questions, agent instructions | ✅ | The golden set was written before any retrieval code |
| 1 | API contract and frontend prototype | ✅ | Spectral-linted contract, generated client, Vitest |
| 2 | Backend core, auth and access control | ✅ | One `acl.allowed_collection_ids` function is the single source of truth |
| 3 | Ingestion pipeline (parse, chunk, PII scan, embed, index) | ✅ | PDF, DOCX, Markdown, HTML |
| 4 | Retrieval, generation and verification, SSE streaming | ✅ | `GET /retrieval/explain` for debugging |
| 5 | Evaluation, quality dashboard, feedback → golden set | ✅ | Real-model nightly eval written but never run (no API key). EvalOps gate verified locally only |
| 6 | Testing depth (unit, integration, ACL leak, prompt injection, E2E) | ✅ | |
| 7 | Containers, CI/CD, deployment | ✅ | Public demo live at <https://citesure-demo.onrender.com> (one free Render container, fake models; [docs/public-demo.md](docs/public-demo.md)). The AWS production pipeline is written but not run |
| 8 | Observability (OpenTelemetry, Prometheus, Grafana, Loki, Tempo, alerts) | ✅ | |
| 9 | Agent extension pack (skills, subagents, MCP server, hooks, plugin, nightly agent) | ✅ | A live Claude Code session using the pack was not recorded |
| 10 | Security scans, threat model, AI data policy, hardening | ✅ | Short-lived signed download links: bound to one user and one document, 60 s, access re-checked on use, never usable as a login token (threat model T23) |
| 11 | Docs, demo video, Substack guide | 🟡 | Demo video in the README; live demo; 17 Substack chapters ready to publish ([substack/README.md](substack/README.md)). Left: publishing them, which needs the owner's Substack account |
| 12 | Private mode and public research | ✅ | Egress guard, allow-list proxy, canary tests; Playwright tests of the public lane run offline in CI with invented papers (`PUBLIC_SOURCES=sample`, refused in prod) |
| 13 | Merge of `document_explorer` (five sub-phases) | ✅ | See section 4 |

## 4. Merged features (from `document_explorer`)

| Capability | Docs |
|---|---|
| Table-aware PDF parsing (PyMuPDF), "looks like a literature question" hint | [rag-design.md](docs/rag-design.md) |
| PDF viewer with the cited quote outlined, personal highlights and notes | [viewer-and-inbox.md](docs/viewer-and-inbox.md) |
| Watched-folder inbox (folder = collection = access rules) | [viewer-and-inbox.md](docs/viewer-and-inbox.md) |
| Open-access full text on demand, budgeted, through the egress guard | [open-access-fulltext.md](docs/open-access-fulltext.md) |
| Reading progress, study sets, learning plans, summarize and compare | [learning-layer.md](docs/learning-layer.md) |
| Tamper-evident audit log and admin dashboard | [audit-dashboard.md](docs/audit-dashboard.md) |
| Optional OIDC login, encrypted upload vault, local OCR | [oidc.md](docs/oidc.md), [vault-and-ocr.md](docs/vault-and-ocr.md) |

Qdrant and Keycloak are not hard dependencies: their capabilities were reimplemented on CiteSure's stack, or added as optional adapters. Private mode keeps CiteSure's rule: hosted models are forbidden; in normal mode they may read public text only.

## 5. Not verified yet

- A real Keycloak or Entra login, real Tesseract OCR, and a Docker build with `WITH_OCR=true` (mocked tests only).
- The learning prompts (summarize, compare, plan) with a real model, and golden questions for them.
- A real-model evaluation run. Published-research answers need Anthropic or OpenAI credit; without credit the screen only says "temporarily unavailable".

## 6. Known gaps

- Inbox files in a folder that matches no workspace are quarantined on disk but shown in no UI (to avoid leaking names across tenants).
- Highlights cannot span two PDF pages; the folder watcher polls instead of using file-system events.
- The open-access full-text cache is shared across workspaces; only the download budget is per workspace.
- The audit chain cannot reveal removal of the newest rows (keep a copy of `head_hash`), and a database owner could rewrite it.
- Learning plans are generated inside one request (up to 12 model calls); study-set items cannot be reordered.
- The table detector needs three or more columns, so a two-column table reads as prose.
- JWT in `localStorage`, in-memory rate limits, no malware scanning, admins can read everything (see [security/threat-model.md](security/threat-model.md)).

## 7. Risks

| Risk | Mitigation |
|---|---|
| Access-control bugs leak data | One ACL function, pre-filter in SQL, leak tests on every endpoint that returns content, a 100% restricted-refusal gate in CI |
| Verification too strict, so too many refusals | Wrongful refusals are a tracked metric (3% with the default configuration) |
| LLM cost | Fake providers in tests and CI, a cheaper verify model, token caps, spend alerts |
| Licensing | PyMuPDF is AGPL-3.0 (fine internally; swap it before offering CiteSure as a service). The demo corpus is fictional |

## 8. Stretch goals

Connectors (Google Drive, Confluence) with incremental sync · multi-turn follow-ups with query rewriting · contextual chunk headers · answer caching keyed by (question, ACL set, corpus version).
