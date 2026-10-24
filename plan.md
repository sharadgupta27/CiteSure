# CiteSure - Project Plan (Project 3)

> Grounded document Q&A with verified citations: enterprise RAG.
> Working name: **CiteSure** ("answers you can verify"). Rubric: [docs/course/final-project-rubric.md](docs/course/final-project-rubric.md). Module 5 deliverable: [docs/course/module5-requirements.md](docs/course/module5-requirements.md).
> Status legend (added during implementation): `[x]` done, `[~]` partly done, `[ ]` not done; notes after a dash record deviations. The agent committed one commit per phase only after the owner asked; nothing was deployed, and the real-model evaluation was not run (no API key).

---

## 1. Problem

Employees waste hours searching policy documents, handbooks and manuals. Generic chatbots answer confidently but can't show *where* an answer came from, so nobody trusts them for HR, compliance or security questions. Many internal RAG systems also leak documents across permission boundaries.

**CiteSure** lets an organization:

1. Upload documents (PDF, DOCX, Markdown, HTML) into access-controlled collections.
2. Ask questions in natural language.
3. Get answers in which **every sentence carries a citation** (document, page or section, and quoted span).
4. Trust that each citation was **verified**: claims the sources don't support are dropped, and if nothing is supported the system says "I don't know".
5. See retrieval quality over time (recall@k, faithfulness, citation precision) on a dashboard.

**Target user:** employees asking questions, and the knowledge-base admin who owns the documents and answer quality.

**Default demo domain:** a company handbook. The [GitLab Handbook](https://handbook.gitlab.com/) is public and CC BY-SA licensed (check the license before shipping). It is real, large and messy, which makes it a good stress test. You can swap in insurance, pharma or another domain you know: only the corpus and the golden set change.

### Expected behavior (happy path)

1. The admin creates a workspace and two collections: `General` (all employees) and `People-Ops-Confidential` (HR role only).
2. The admin uploads 200 handbook pages. Ingestion runs in the background and the UI shows per-document status: parsed → chunked → embedded → ready.
3. An employee asks *"How many days of parental leave do I get?"*
4. CiteSure retrieves with hybrid search, reranks, generates an answer as structured claims and verifies each claim against its cited chunk.
5. The UI shows the answer with numbered citations. Clicking one opens the source with the quoted span highlighted.
6. An employee **without** the HR role asks about something only in `People-Ops-Confidential` and gets "I don't have information on that". Confidential chunks are never retrieved.
7. The user gives a thumbs-down with a comment. The admin sees it in the feedback queue and promotes it to the golden evaluation set.
8. The admin opens **Quality**, runs the eval suite, and compares configurations (for example, hybrid + rerank vs vector-only).

### Non-goals (MVP)

- Connectors to Google Drive, Confluence or SharePoint (stretch goal)
- Multi-turn conversational memory beyond the current thread (stretch goal)
- OCR for scanned PDFs
- SSO/SAML (local auth plus roles only)
- Fine-tuning embedding models

---

## 2. Architecture

```text
                       ┌──────────────────────────── FastAPI (api) ────────────────────────────┐
┌──────────────┐ REST  │                                                                        │
│ React (Vite) │──────▶│  /ask ─▶ QueryPipeline                                                 │
│  frontend/   │◀──SSE─│          1. ACL filter (user → allowed collection ids)                 │
└──────────────┘       │          2. Hybrid retrieve: pgvector top-k ∪ Postgres FTS top-k       │
                       │          3. Fuse (Reciprocal Rank Fusion) → rerank (cross-encoder)      │
                       │          4. Generate structured answer {claims[], citations[]}         │
                       │          5. Verify: quote-match (deterministic) + entailment (LLM)     │
                       │          6. Drop unsupported claims → answer or "I don't know"         │
                       │                                                                        │
                       │  /documents ─▶ enqueue ingestion job                                   │
                       └───────────────┬────────────────────────────────────────────────────────┘
                                       │                         ┌──────────────────────────┐
                                       ▼                         │ Postgres 16 + pgvector   │
                       ┌────────────────────────────┐            │ docs, chunks (embedding, │
                       │ Worker (same image)        │◀──────────▶│ tsvector), jobs, ACLs,   │
                       │ parse → clean → chunk →    │            │ answers, feedback, evals │
                       │ PII scan → embed → index   │            └──────────────────────────┘
                       └────────────────────────────┘
       Providers behind interfaces:  LLMProvider (Anthropic | Fake)
                                     Embedder (fastembed local | Voyage | Fake)
                                     Reranker (fastembed cross-encoder | none)
       File storage: local volume (dev) / S3 (prod) behind BlobStore
```

**Key design decisions**

| Decision | Choice | Why |
|---|---|---|
| Vector store | **pgvector in the same Postgres** | One database, ACL filters run in SQL alongside vector search, and there's less to operate |
| Keyword search | Postgres full-text search (`tsvector`, GIN index) | Hybrid search without Elasticsearch; catches exact terms such as policy IDs and acronyms |
| Fusion | Reciprocal Rank Fusion | Needs no score normalization, is a well-known baseline and easy to explain |
| Embeddings | `fastembed` (local ONNX, e.g. `BAAI/bge-small-en-v1.5`) by default; Voyage optional | No API key needed for demo or CI, and costs nothing |
| Answer format | Structured output: list of claims, each with chunk ids + quoted span | Makes deterministic citation verification possible |
| Verification | Stage 1 checks the quote exists in the chunk (fuzzy match); stage 2 runs an entailment check with a cheaper model | Catches fabricated quotes cheaply; the LLM check catches "real quote, wrong conclusion" |
| Access control | **Pre-filter** by allowed collection ids inside the retrieval SQL | Post-filtering leaks through scores, counts and timing, and can starve results |
| Background jobs | Postgres jobs table + `SKIP LOCKED` | Same proven pattern as Project 1, with no Redis |
| Contract | `openapi.yaml` is the source of truth; TS client generated from it | Rubric criteria 4–5 |

---

## 3. Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React 18 + TypeScript + Vite, TanStack Query, React Router, Tailwind, `openapi-typescript` + `openapi-fetch`, a PDF viewer (`react-pdf`) for citation highlighting |
| Frontend tests | Vitest + React Testing Library; Playwright for E2E |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, `uv` |
| Ingestion | `pypdf`, `python-docx`, `markdown-it-py`, `beautifulsoup4`, heading-aware chunker (custom) |
| Retrieval | pgvector (HNSW index), Postgres FTS, `fastembed` (embeddings + reranker) |
| LLM | Anthropic SDK behind `LLMProvider`; `ANSWER_MODEL` and `VERIFY_MODEL` set by env |
| Evaluation | Custom harness (recall@k, MRR, faithfulness, citation precision/recall, refusal accuracy); optional export to EvalOps (Project 1) |
| Database | PostgreSQL 16 + pgvector (the `pgvector/pgvector:pg16` image) |
| Containers | Docker, Docker Compose (`api`, `worker`, `frontend`/nginx, `db`) |
| CI/CD | GitHub Actions: lint → test → build → push to GHCR → deploy |
| Hosting | AWS EC2 (t3.medium, since embedding and reranking run locally) + Compose behind Caddy; S3 for uploads. Stretch: ECS + RDS |
| Observability | OpenTelemetry → Prometheus / Loki / Tempo / Grafana; per-stage latency spans |
| Security | gitleaks, Semgrep, Trivy, pip-audit, npm audit; regex PII scanner at ingestion (Presidio optional) |

---

## 4. Data Model

```text
users              id, email, password_hash, created_at
workspaces         id, name, created_at
memberships        user_id, workspace_id, role ENUM{admin, member}
groups             id, workspace_id, name                         -- e.g. "hr"
group_members      group_id, user_id
collections        id, workspace_id, name, visibility ENUM{workspace, groups}
collection_groups  collection_id, group_id                        -- who may read
documents          id, collection_id, title, filename, mime, sha256, blob_key,
                   status ENUM{queued, parsing, embedding, ready, failed},
                   page_count, error, uploaded_by, created_at
chunks             id, document_id, collection_id (denormalized for ACL filter),
                   ord, text, heading_path, page_start, page_end, char_start, char_end,
                   token_count, embedding VECTOR(384), tsv TSVECTOR, pii_flags JSONB
jobs               id, kind, payload JSONB, status, attempts, run_after, locked_at, error
threads            id, user_id, workspace_id, created_at
answers            id, thread_id, question, answer_json JSONB, status ENUM{answered, refused},
                   retrieved_chunk_ids[], config_snapshot JSONB,
                   latency_ms_by_stage JSONB, tokens_in, tokens_out, cost_usd, created_at
feedback           id, answer_id, user_id, rating SMALLINT, comment, created_at
golden_questions   id, workspace_id, question, expected_answer, expected_chunk_ids[],
                   answerable BOOL, source ENUM{manual, feedback}, tags[]
eval_runs          id, workspace_id, config JSONB, status, metrics JSONB, created_at
eval_items         id, eval_run_id, golden_question_id, retrieved_chunk_ids[],
                   answer_json JSONB, scores JSONB
```

`answer_json` shape (also the LLM's structured-output schema):

```json
{
  "claims": [
    { "text": "Employees receive 16 weeks of paid parental leave.",
      "citations": [{ "chunk_id": "c_812", "quote": "16 weeks of paid parental leave" }],
      "verified": true, "verification": { "quote_match": 0.98, "entailment": "supported" } }
  ],
  "refusal": null
}
```

---

## 5. API Surface (`/api/v1`)

| Method & path | Purpose |
|---|---|
| `POST /auth/register`, `POST /auth/login` | Auth (JWT) |
| `GET/POST /workspaces`, `…/members`, `…/groups` | Workspace admin |
| `GET/POST/PATCH/DELETE /workspaces/{id}/collections` | Collections + group access |
| `POST /collections/{id}/documents` (multipart), `GET /collections/{id}/documents` | Upload and list documents |
| `GET /documents/{id}`, `DELETE /documents/{id}`, `POST /documents/{id}/reindex` | Status, removal, reindex |
| `GET /documents/{id}/file` | Signed or streamed original for the citation viewer (ACL-checked) |
| `GET /chunks/{id}` | Chunk text and location (ACL-checked) |
| `POST /ask` | Question → verified answer (JSON) |
| `POST /ask/stream` | The same, as Server-Sent Events: `stage` → `token` → `final` |
| `GET /threads`, `GET /threads/{id}` | History |
| `POST /answers/{id}/feedback` | Thumbs up/down + comment |
| `GET/POST/PATCH/DELETE /workspaces/{id}/golden-questions` | Eval set; `POST …/from-feedback/{id}` promotes feedback |
| `POST /workspaces/{id}/eval-runs`, `GET /eval-runs/{id}`, `GET /eval-runs/compare?base=&head=` | Evaluation |
| `GET /retrieval/explain` (admin) | Per-stage candidates and scores for a query |
| `GET /healthz`, `GET /metrics` | Ops |

---

## 6. Repository Layout

```text
README.md
product-spec.md
AGENTS.md
CLAUDE.md
plan.md
openapi.yaml
docker-compose.yml
docker-compose.prod.yml
frontend/
backend/
  app/
    api/            routers (HTTP only)
    services/       ask, ingest, eval, acl
    rag/
      parsing/      one parser per mime type
      chunking/     heading-aware chunker
      retrieval/    vector, fts, fusion, rerank
      generation/   prompts/, structured output schema
      verification/ quote_match, entailment
    repositories/   all DB access
    models/  schemas/  llm/  embeddings/  storage/  worker/
  migrations/
  tests/{unit,integration}/
  evals/            golden sets (JSONL), experiment configs
e2e/
corpus/             demo corpus fetch script + license notes (not the docs themselves)
.github/workflows/{ci.yml, deploy.yml, rag-eval.yml}
ops/  security/
docs/
  ai-workflow.md  architecture.md  rag-design.md  eval-results.md
  agent-extension-pack.md  permissions.md  demo.md
agent-capabilities/
  ingest-new-doc-type/SKILL.md
  add-golden-question/SKILL.md
  tune-retrieval/SKILL.md
  review-api-change/SKILL.md
  subagents/{retrieval-debugger.md, citation-auditor.md, api-contract-reviewer.md}
agent-hooks/
mcp-server/{server.py, README.md}
plugins/citesure-agent-pack/
custom-agent/{agent.py, README.md}
substack/
```

---

## 7. Phases

Each phase ends with a commit, a `docs/ai-workflow.md` entry and a Substack chapter draft. Effort assumes part-time work (about 10 h/week).

### Phase 0: Spec, Corpus & Agent Context (≈ 0.5 week)
- [x] `git init`, `.gitignore`, license - repository exists; one commit per phase was made at the owner's request (earlier phase commits do not build alone: files were split by directory afterwards)
- [x] `product-spec.md`: personas (employee, admin), user stories, acceptance criteria
- [x] Choose the domain and corpus; write a fetch script in `corpus/` and record the license
- [x] **Write 40 golden questions before writing any RAG code**: 30 answerable (with expected source pages), 10 unanswerable or permission-restricted
- [x] `AGENTS.md` and `CLAUDE.md`; start `docs/ai-workflow.md`

**Done when:** the golden set exists. It is the target that every later phase is measured against.
**Rubric:** 1, 2 · **Guide chapter:** *"Start RAG with the eval set, not the vector DB"*. Concepts: why golden questions come first, answerable vs unanswerable questions.

### Phase 1: API Contract & Frontend Prototype (≈ 1 week)
- [x] `openapi.yaml` (including SSE documented as `text/event-stream`), linted with Spectral
- [x] Vite + React + TS; generated client in `frontend/src/api/`; Prism mock server - Prism mock script `npm run mock` added, not exercised in this session
- [x] Pages: Login, Workspace admin (collections, groups, members), Documents (upload + status), **Ask** (answer + citation chips), **Source viewer** (PDF/HTML with highlighted span), Feedback queue, Quality dashboard - deviation: the source viewer highlights the cited quote inside the chunk text; there is no page-image PDF viewer
- [x] Vitest tests: citation rendering, highlight-range mapping, SSE event reducer

**Done when:** the full UI flow works against mocks.
**Rubric:** 4, 5 · **Guide chapter:** *"Designing a UI people trust: how citations change the UX of AI answers"*.

### Phase 2: Backend Core, Auth & ACL (≈ 1 week)
- [x] FastAPI app factory, settings, layering `api → services → repositories`
- [x] Models, Alembic migrations including `CREATE EXTENSION vector`
- [x] Auth (JWT), workspaces, groups, collections, membership
- [x] `acl.allowed_collection_ids(user, workspace)`: the **single** source of authorization truth
- [x] Upload endpoint: validates type by magic bytes, enforces a size limit, deduplicates by sha256, stores via `BlobStore`
- [x] Contract drift test (FastAPI schema vs `openapi.yaml`)

**Done when:** the frontend works against the real backend for everything except Ask.
**Rubric:** 6, 7 · **Guide chapter:** *"Permission-aware RAG: why access control belongs inside retrieval"*.

### Phase 3: Ingestion Pipeline (≈ 1.5 weeks)
- [x] Worker with the jobs table, retries and backoff
- [x] Parsers: PDF (page-aware), DOCX, Markdown, HTML. Normalize to `Section{heading_path, text, page, char offsets}`
- [x] Heading-aware chunker: ~400 tokens with ~15% overlap; never split mid-sentence; keep page and char offsets so citations can be highlighted
- [x] PII scan (emails, phone numbers, ID patterns): flag chunks, and optionally redact before embedding
- [x] `Embedder` interface with fastembed (default), Voyage (optional) and Fake implementations; batch embedding
- [x] Indexes: HNSW on `embedding`, GIN on `tsv`, btree on `collection_id`
- [x] Ingest the demo corpus and record throughput (docs/min) in `docs/rag-design.md`

**Done when:** 200 documents reach `ready` and the status UI reflects every stage.
**Rubric:** 6 · **Guide chapter:** *"Chunking is a product decision: parsing, chunking and embedding explained"*.

### Phase 4: Retrieval, Generation & Verification (≈ 2 weeks)
- [x] Vector search and FTS search, both pre-filtered by allowed collection ids
- [x] Reciprocal Rank Fusion, then an optional cross-encoder rerank (top 30 → top 6)
- [x] Generation prompt: sources wrapped in delimited, id-tagged blocks; instructions to cite or refuse; structured-output schema from §4
- [x] Verification stage 1 (`quote_match`): the quoted span must fuzzy-match text in the cited chunk (≥ 0.9)
- [x] Verification stage 2 (`entailment`): `VERIFY_MODEL` judges supported, partial or unsupported for each claim and its cited chunk
- [x] Policy: drop unsupported claims. If no verified claims remain, return a refusal with "closest sources" links
- [x] SSE streaming of stage events (`retrieving`, `generating`, `verifying`) and the final answer
- [x] `GET /retrieval/explain` for debugging
- [x] Per-stage latency, token and cost capture in `answers`

**Done when:** the golden set runs end to end and the citation viewer highlights the correct span.
**Rubric:** 6 · **Guide chapters:** *"Hybrid search and reranking, explained with real failures"* and *"Making LLMs cite their sources, and catching them when they lie"*.

### Phase 5: Evaluation & Quality Dashboard (≈ 1 week)
- [x] Eval harness over the golden set. Metrics:
  - **Retrieval:** recall@k and MRR (using expected chunk or page ids)
  - **Answer:** correctness (LLM judge vs expected answer) and faithfulness (share of verified claims)
  - **Citations:** precision (cited chunk supports the claim) and recall
  - **Safety:** refusal accuracy on unanswerable and restricted questions (target 100% on restricted)
- [x] **Experiment matrix** in `backend/evals/experiments.yaml`: vector-only vs hybrid, ± rerank, chunk size 256/400/800. Results table in `docs/eval-results.md` - deviation: ran 64/128-token chunk variants because every demo page is shorter than 256 tokens (see eval-results.md)
- [x] Quality dashboard UI: metrics per eval run and a compare view
- [x] Feedback → golden-set promotion flow
- [x] `.github/workflows/rag-eval.yml`: runs the eval with Fake embedder/LLM for determinism on PRs, and the real-model eval on a nightly schedule - written and every command run locally; **not run on GitHub**; the real-model nightly run was never executed (no API key)
- [x] Stretch: push results to EvalOps (Project 1) through its `POST /gate/ingest` API - see `docs/evalops-integration.md`; verified locally against a real EvalOps, **not run on GitHub** (needs the `EVALOPS_*` secrets and a hosted EvalOps)

**Done when:** the README shows a real before/after table, for example *"hybrid + rerank raised recall@5 from 0.71 to 0.88"*.
**Rubric:** 9, 11 · **Guide chapter:** *"Measuring RAG: recall, faithfulness and the metrics that actually matter"*.

### Phase 6: Testing Depth (≈ 1 week)
- [x] Unit tests: parsers (fixture files), chunker offsets, RRF math, quote matcher, ACL function, refusal policy
- [x] Integration tests (`@pytest.mark.integration`, testcontainers `pgvector/pgvector:pg16`): upload → ingest → ask → verify; **ACL leak tests** (a restricted user can never retrieve restricted chunks through any endpoint, including `/chunks/{id}`, `/documents/{id}/file` and `/retrieval/explain`)
- [x] Prompt-injection tests: poisoned documents ("ignore previous instructions…") must not change system behavior or leak other sources
- [x] Playwright E2E for the happy path, including the restricted-user refusal

**Rubric:** 4, 6, 9 · **Guide chapter:** *"Testing a RAG system: unit, integration, adversarial"*.

### Phase 7: Containerize, Deploy, CI/CD (≈ 1 week)
- [x] Multi-stage Dockerfiles with the fastembed models baked into the image (no download at runtime) - `WITH_ML=true` build arg implemented; the ML image was not built in this session
- [x] `docker-compose.yml` (dev) and `docker-compose.prod.yml`; a seed script loads a small demo corpus and demo users with different roles
- [x] `ci.yml`: lint, type-check, unit, integration, E2E, security scans, image build
- [x] `deploy.yml`: on `main` with green tests, push to GHCR, deploy to EC2, migrate, health check - written and validated locally; **not run, nothing deployed**
- [x] S3 `BlobStore` in prod; uploads in the public demo are disabled or limited - `S3BlobStore` implemented (optional boto3); not exercised against real S3; production compose has `UPLOADS_ENABLED=false`
- [ ] Public demo with pre-ingested corpus and two demo logins (employee, HR) - **NOT DONE**: needs an AWS account and explicit approval; runbook in docs/deployment.md

**Rubric:** 8, 10, 11, 14 · **Guide chapter:** *"Deploying a RAG app on a budget: local embeddings, one Postgres, one VM"*.

### Phase 8: Observability (≈ 0.5 week)
- [x] OpenTelemetry spans per pipeline stage: acl, vector, fts, fuse, rerank, generate, verify
- [x] Grafana: p50/p95 latency per stage, refusal rate, verification drop rate, cost per answer, ingestion queue depth
- [x] Alert: refusal rate or verification-drop rate spikes (a signal of retrieval regression or corpus problems)
- [x] Separate dev and prod configs

**Rubric:** 13 · **Guide chapter:** *"Observing RAG in production: what to graph and what to alert on"*.

### Phase 9: Agent Extension Pack (≈ 1.5 weeks)

| Requirement | Implementation |
|---|---|
| Project instructions | `AGENTS.md` + `CLAUDE.md` |
| Reusable workflows | `ingest-new-doc-type` (add a parser + fixtures + tests), `add-golden-question` (from a bug report or feedback), `tune-retrieval` (run the experiment matrix and summarize), `review-api-change` |
| Specialized subagents | `retrieval-debugger` (uses MCP `explain_retrieval` to diagnose a bad answer), `citation-auditor` (read-only; checks sampled answers' citations), `api-contract-reviewer` |
| MCP server | Tools: `list_collections`, `search_corpus`, `get_chunk`, `explain_retrieval`, `ask`, `run_eval`. Resources: `citesure://documents/{id}`. Prompt: `diagnose-bad-answer`. Authenticates as a **scoped service user**, so ACLs still apply to the agent |
| Hooks / guardrails | PreToolUse: block reading `.env*` and `corpus/raw/`; block edits to `backend/evals/golden*.jsonl` unless the `add-golden-question` skill is active (guards against "fixing" evals to pass). PostToolUse: ruff/prettier. Stop: fast tests + ACL unit tests |
| Plugin | `plugins/citesure-agent-pack/` bundles the skills, subagents, hooks and MCP config |
| Custom agent | `custom-agent/agent.py`: nightly job that runs evals, diffs against the last run, and opens an issue with regressions and suspected causes from `explain_retrieval` |
| Permissions note | `docs/permissions.md`: agent identities, MCP scopes, why the agent is subject to the same ACLs as users |
| Parallel work | Two subagents in separate worktrees, for example a new DOCX table parser and a frontend citation-viewer fix |

**Demo** (`docs/demo.md`): a user reports a bad answer. The agent reads the instructions, invokes `add-golden-question`, `retrieval-debugger` calls `explain_retrieval` over MCP and finds a chunking issue, the fix is made, a hook blocks an attempt to edit the golden answer, and you review the final diff.
**Rubric:** 12 · **Guide chapters:** *"Giving coding agents safe access to your RAG system with MCP"* and *"Hooks that stop agents from gaming your evals"*.

### Phase 10: Security, Audit & Hardening (≈ 0.5 week)
- [x] Deterministic scans (gitleaks, Semgrep, Trivy, pip-audit, npm audit) with outputs in `security/`
- [x] AI PR audit output plus your accept/reject notes
- [x] Threat model (`security/threat-model.md`):
  - indirect prompt injection via documents
  - cross-collection data leakage
  - PII exposure
  - malicious uploads (zip bombs, polyglot files)
  - MCP over-permissioning
- [x] `security/ai-data-policy.md`: what is sent to which LLM, PII handling, retention, deletion (removing a document removes its chunks and embeddings)
- [~] App hardening: rate limits, upload limits, strict CORS, short-lived signed file URLs - rate limits, upload limits, strict CORS done; downloads require auth instead of signed URLs (not implemented)

**Rubric:** 13 · **Guide chapter:** *"The RAG threat model: prompt injection, leakage and PII"*.

### Phase 11: Docs, Demo & Launch (≈ 0.5 week)
- [x] README: problem, screenshots/GIF, architecture, live URL, **eval results table**, run/test/deploy steps
- [x] `docs/rag-design.md`: every design decision with the experiment that justified it
- [ ] 2-minute demo video, including the permission-denied scenario - **NOT DONE**: script and captured outputs in docs/demo.md; no video recorded
- [~] Publish the Substack series; write resume bullets with the numbers - chapters drafted in `substack/`; not published (owner publishes)

**Rubric:** 1, 3, 14

---

### Phase 12: Private mode and public research (added 2026-10-23)
Requirement: company documents never leave the system; published papers and web pages are still searchable; the EvalOps link keeps working when deployed for free.
- [x] Local model for the internal lane (`LocalProvider`, any OpenAI-compatible server) and boot checks that refuse a hosted internal model, Voyage embeddings, or a "local" URL on a public address (`PRIVATE_MODE`)
- [x] Egress guard (PII, secrets, internal addresses, never-share terms, canaries, 6-word copy detection against every stored document, internal names) on the question and on the keyword-only query
- [x] `EgressClient`: the only HTTP gateway (https only, allow-list or public-only, SSRF checks, redirects re-validated, size cap)
- [x] Public sources: arXiv, Crossref, OpenAlex, Europe PMC, Semantic Scholar, and an open-web source (Claude web search finds URLs, CiteSure fetches the pages)
- [x] `scope` on `/ask`, preview endpoint, status endpoint, `egress` and `notices` on every answer; routing (`choose_llm`) and runtime safety net (`ensure_lane_safe`); `answer_v2` prompt for mixed sources
- [x] UI: scope selector, editable keyword preview, public badges, original-source panel, what-was-sent disclosure
- [x] Network enforcement: `docker-compose.private.yml` (internal network with no route out, Squid allow-list proxy, Ollama), `deploy/verify-isolation.sh`
- [x] Tests: guard, client, connectors, local provider, routing, deploy config, 13 integration tests with a planted canary; CI job for the proxy policy
- [x] Observability: egress metrics, Grafana panels, privacy alerts
- [x] EvalOps: redacted export for real data, self-host compose with Tailscale Funnel / Cloudflare Tunnel profiles, free deployment guide; verified against a live EvalOps
- [~] Real-model checks - **NOT RUN**: no API key and no downloaded local model were used. The Claude public lane and the web source are tested with fakes and mock networks; the local model path is tested against a mock server. Run `ollama-pull` and the evaluation with `LLM_PROVIDER=local`, then set `PUBLIC_LLM_PROVIDER=anthropic`, before trusting answer quality
- [ ] A Playwright test of the public lane - needs live internet; not added

**Rubric:** 3, 13

---

## 8. Rubric Coverage

| # | Criterion | Where it is satisfied |
|---|---|---|
| 1 | Problem description | README, product-spec.md |
| 2 | AI-assisted workflow | docs/ai-workflow.md, AGENTS.md |
| 3 | Technologies & architecture | README, docs/architecture.md, docs/rag-design.md |
| 4 | Frontend (3 pts) | Phase 1 + Vitest |
| 5 | API contract | openapi.yaml + drift test |
| 6 | Backend (3 pts) | Phases 2–4 + pytest |
| 7 | Database | Postgres + pgvector, Alembic, env-specific config |
| 8 | Containerization | docker-compose.yml |
| 9 | Integration tests | backend/tests/integration (ACL leak + injection), e2e/ |
| 10 | Deployment | AWS EC2 public URL |
| 11 | CI/CD | ci.yml + deploy.yml + rag-eval.yml |
| 12 | Agent extension pack | Phase 9 |
| 13 | Security / audit / DevOps | security/, ops/, threat model |
| 14 | Reproducibility | README "Run / Test / Deploy" sections + seed script |

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Messy PDFs break parsing | Start with Markdown/HTML corpus; PDF fixtures with known layouts; record failures per document |
| Verification is too strict, so it refuses too often | Track the refusal rate on answerable questions as a metric; tune thresholds with the golden set |
| Local embedding and reranking is slow on a small VM | Batch at ingestion; rerank only the top 30; t3.medium; cache query embeddings |
| LLM cost | Fake providers in tests and CI; cheaper `VERIFY_MODEL`; per-request token caps |
| ACL bugs leak data | Single `acl` function, pre-filter in SQL, dedicated leak tests on every endpoint that returns content |
| Corpus licensing | Use public, permissively licensed corpus; store a fetch script, not the documents |

## 10. Stretch Goals
- Connectors (Google Drive, Confluence) with incremental sync
- Multi-turn follow-ups with query rewriting
- Contextual chunk headers or late chunking, measured against the baseline
- Answer caching keyed by (question embedding, ACL set, corpus version)
- EvalOps integration as the CI quality gate
