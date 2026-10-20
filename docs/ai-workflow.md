# AI-Assisted Development Workflow

This project was built with a coding agent (Claude Code) working from written instructions. This page documents **how**, so the process can be reviewed and repeated (rubric criterion 2).

## Context files the agent reads

| File | Purpose |
|---|---|
| `CLAUDE.md` / `AGENTS.md` | Non-negotiables, commands, conventions, boundaries |
| `plan.md` | Phased roadmap with checkboxes the agent ticks |
| `product-spec.md` | User stories and acceptance criteria |
| `openapi.yaml` | API contract (source of truth) |
| `docs/course/*` | The course rubric and Module 5 requirements |

## Working method

1. **One phase at a time.** The agent restates the phase goal in a few bullets, then implements.
2. **Evals before RAG code.** The 40-question golden set was written (Phase 0) before any retrieval code.
3. **Contract first.** `openapi.yaml` was written before the frontend and backend; a drift test keeps them honest.
4. **Fakes everywhere in tests.** `FakeProvider` + `FakeEmbedder` make tests deterministic and free.
5. **Run it, don't assume it.** Every task ends with tests actually executed; failures are fixed, not hidden.
6. **Human review points.** The human reviews: dependency additions, schema/ACL/CI changes, and every diff before commit. The agent never commits or deploys on its own.

## Log

Each entry: goal → prompt/delegation → what the AI produced → what the human reviewed or changed → verification.

### 2026-10-20 — Phase 0: spec, corpus, golden set

- **Goal:** project scaffold, demo corpus, 40 golden questions, agent instructions.
- **Prompt / delegation:** "Implement the CiteSure project using `plan.md`, follow `CLAUDE.md`, satisfy the final-project rubric and the Module 5 extension pack, and write a beginner-friendly Substack guide."
- **AI produced:** `.gitignore`, `LICENSE`, `product-spec.md`, `AGENTS.md`, a fictional 20-page "Acme Robotics" handbook (16 public + 4 HR-only pages), `backend/evals/golden.jsonl` (30 answerable, 10 unanswerable/restricted), `corpus/validate_golden.py`, `corpus/fetch_gitlab_handbook.py`.
- **Human review:** *(to fill in by the project owner)* check the corpus facts and that the golden questions match your idea of "hard" questions.
- **Verification:** `python corpus/validate_golden.py` → `40 questions (30 answerable), 0 problems`. Every expected quote exists verbatim in the corpus.
- **Decision recorded:** golden questions store `expected_quotes` (document + exact quote) instead of chunk ids. Chunk ids change every time the chunker changes; quotes don't. The eval harness resolves quotes to chunks at run time. This is a deliberate deviation from `plan.md` §4 (`expected_chunk_ids`).

> Prompts below are one session's delegations in summary (the same standing instruction, then "continue" when the context ran out). **Human review** cells are left for the project owner: the agent cannot attest that a human looked at anything.

### 2026-10-20 — Phase 1: API contract and frontend prototype

- **Goal:** `openapi.yaml` first, then a typed client and the UI pages.
- **AI produced:** `openapi.yaml` (31 operations, `text/event-stream` documented, `error` event added later), `.spectral.yaml`, the React app (`frontend/src/{api,auth,components,pages,lib}`), generated `schema.d.ts`, 59 Vitest tests (citation rendering, highlight-range mapping, SSE reducer), ESLint rule that forbids `fetch` outside `src/api`.
- **Human review:** *(owner to fill in)* contract field names, page flow, copy.
- **Verification:** Spectral lint clean; `npm run typecheck`, `lint`, `test`, `build` pass. Deviation: the frontend was built after the backend (so the contract could be checked against a running server). Deviation: the source viewer highlights the quote inside the chunk text, with no PDF page images.
- **New dependencies:** react-router, TanStack Query, openapi-typescript / openapi-fetch, Tailwind, Vitest + Testing Library (all from the plan); `react-router` was later moved to v7 after `npm audit`.

### 2026-10-20 — Phase 2: backend core, auth and access control

- **Goal:** FastAPI app factory, models, migrations, JWT auth, the single ACL function, upload validation, contract drift test.
- **AI produced:** `backend/app/**`, migration `0001`, `services/acl.py` (one decision function), uploads validated by magic bytes with a size cap and sha256 de-duplication, `tests/unit/test_contract.py`.
- **Human review:** *(owner to fill in)* **ACL rules and schema are the review priority.** Decision to confirm: workspace admins read every collection (documented in `docs/permissions.md`).
- **Verification:** unit tests, `alembic check` in the integration suite, drift test between FastAPI and `openapi.yaml`.
- **New dependencies beyond the plan list:** `pyjwt`, `bcrypt`, `python-multipart`, `pydantic-settings`, `asyncpg`, `pgvector`, `rapidfuzz` (quote matching), `prometheus-client`, `opentelemetry-*`, `testcontainers`.

### 2026-10-20 — Phase 3: ingestion

- **Goal:** worker, parsers, heading-aware chunker with exact offsets, PII scan, embedder interface, indexes.
- **AI produced:** Postgres jobs table with `FOR UPDATE SKIP LOCKED`, retries with backoff (10/20/40 s) and stuck-job recovery; PDF/DOCX/Markdown/HTML parsers; chunker; regex PII scan; FakeEmbedder (384-d feature hashing) and fastembed adapter; HNSW, GIN and btree indexes.
- **Bugs found by tests:** tsvector bulk insert failed with executemany (switched to ORM inserts); name shadowing in `detect`.
- **Verification:** parser fixtures, chunker offset tests, 8-worker no-double-claim test. Throughput recorded in `docs/rag-design.md`.

### 2026-10-20 — Phase 4: retrieval, generation and verification

- **AI produced:** vector + FTS search with the ACL filter in SQL, RRF (k=60), rerank 30 to 6, id-tagged source prompt with neutralised delimiters, structured claims, quote match (rapidfuzz, at least 0.9, at least 12 characters) and entailment, refusal policy, SSE stages, `/retrieval/explain`, per-stage latency.
- **Bugs found by tests:** a forged `<system>` tag passed through the prompt builder (fixed); an SSE test that matched a substring ("26") by accident (replaced with a parser helper).
- **Verification:** unit tests for the verifier modes (extractive, hallucinate, mismatch, obedient) and 6 injection tests.

### 2026-10-20 — Phase 5: evaluation

- **AI produced:** harness with personas and the metrics in `docs/eval-results.md`, experiment matrix, baseline regression gate (tolerance 0.02), quality UI and compare view, feedback-to-golden promotion, `rag-eval.yml`.
- **Bugs found by the harness's own checks:** nondeterministic tie-breaking, a worker stealing the evaluation's jobs, a persona crash in the member list. All fixed with regression tests.
- **Honest limits:** all numbers use the fake providers; the real-model run was **not executed**. The golden set was never edited to make a metric pass.
- **Deviation:** chunk-size experiment ran 64/128/default because demo pages are shorter than 256 tokens.

### 2026-10-20 — Phase 6: testing depth

- **AI produced:** 94 unit + 73 integration tests (17 ACL leak tests on every content endpoint), 6 prompt-injection tests, 9 Playwright E2E tests.
- **Verification:** all green at the end of the session; E2E 9/9 after a final rebuild.

### 2026-10-20 — Phase 7: containers and CI/CD

- **AI produced:** multi-stage Dockerfiles (non-root; `WITH_ML`, `WITH_S3` args), `docker-compose.yml`, `docker-compose.prod.yml`, Caddyfile, `ci.yml`, `rag-eval.yml`, `deploy.yml`, all actions pinned to commit SHAs.
- **Verification:** the stack was run and checked with `docker compose ps` and `/healthz`. **The workflows were not run on GitHub and nothing was deployed.** The owner decides on AWS (`docs/deployment.md`).
- **Human review:** *(owner to fill in)* every workflow, the production compose file and secrets handling. CI and deploy files are security-sensitive.

### 2026-10-20 — Phase 8: observability

- **AI produced:** Prometheus metrics, OTel tracing, Loki/Promtail, Tempo, Grafana dashboard, 8 alert rules (checked with `promtool`).
- **Verification:** targets up, rules loaded, traces received by Tempo, dashboard screenshot captured. The logs panel exposed a short dev JWT secret (fixed).

### 2026-10-20 — Phase 9: agent extension pack

- **AI produced:** 4 skills, 3 read-only subagents, MCP server (6 tools), 3 hooks + append-only check, plugin, nightly custom agent, `docs/permissions.md`, `docs/demo.md`.
- **Verification:** 60 hook tests, 12 MCP tests, 13 agent tests; live MCP check as a plain-member service user (restricted content invisible, `run_eval` returns 403).
- **Not recorded:** a live Claude Code session choosing the skill and spawning the subagent (marked "to rehearse" in the demo).
- **Bug found by tests:** the first guard failed open on an unusual path spelling (now matched by path tail).

### 2026-10-20 — Phase 10: security

- **AI produced:** scans (gitleaks, Semgrep, Trivy, pip-audit, npm audit) in `security/scan-results/`, `scan-summary.md`, `ai-pr-audit.md` (fix / accept / reject), threat model (16 threats), AI data policy.
- **Result:** Semgrep 35 to 1 (accepted, A10); Trivy fs clean after the nginx fix; manual review found 4 more issues (document text in DB errors, short dev secret, worker healthcheck, quotes left in stored answers), all fixed with tests.
- **Human review:** *(owner to fill in)* countersign `ai-pr-audit.md`. A review by the same agent that wrote the code is not independent.

### 2026-10-20 — Phase 11: docs and Substack

- **AI produced:** README, architecture, rag-design, eval-results, deployment docs, 14 Substack chapters, 12 generated figures, 12 screenshots of the running app.
- **Corrections made on review of its own text:** a fabricated anecdote in chapter 1 was removed; test counts and retry timings were checked against the code.
- **Not done:** demo video, public URL, publishing the series.
