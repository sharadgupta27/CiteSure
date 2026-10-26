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
6. **Human review points.** The human reviews: dependency additions, schema/ACL/CI changes, and every diff before commit. The agent never commits or deploys on its own: the per-phase commits were made only on the owner's explicit request, after the work was finished.

## Log

Each entry: goal → prompt/delegation → what the AI produced → what the human reviewed or changed → verification.

### 2026-10-20 - Phase 0: spec, corpus, golden set

- **Goal:** project scaffold, demo corpus, 40 golden questions, agent instructions.
- **Prompt / delegation:** "Implement the CiteSure project using `plan.md`, follow `CLAUDE.md`, satisfy the final-project rubric and the Module 5 extension pack, and write a beginner-friendly Substack guide."
- **AI produced:** `.gitignore`, `LICENSE`, `product-spec.md`, `AGENTS.md`, a fictional 20-page "Acme Robotics" handbook (16 public + 4 HR-only pages), `backend/evals/golden.jsonl` (30 answerable, 10 unanswerable/restricted), `corpus/validate_golden.py`, `corpus/fetch_gitlab_handbook.py`.
- **Human review:** *(to fill in by the project owner)* check the corpus facts and that the golden questions match your idea of "hard" questions.
- **Verification:** `python corpus/validate_golden.py` → `40 questions (30 answerable), 0 problems`. Every expected quote exists verbatim in the corpus.
- **Decision recorded:** golden questions store `expected_quotes` (document + exact quote) instead of chunk ids. Chunk ids change every time the chunker changes; quotes don't. The eval harness resolves quotes to chunks at run time. This is a deliberate deviation from `plan.md` §4 (`expected_chunk_ids`).

> Prompts below are one session's delegations in summary (the same standing instruction, then "continue" when the context ran out). **Human review** cells are left for the project owner: the agent cannot attest that a human looked at anything.

### 2026-10-20 - Phase 1: API contract and frontend prototype

- **Goal:** `openapi.yaml` first, then a typed client and the UI pages.
- **AI produced:** `openapi.yaml` (31 operations, `text/event-stream` documented, `error` event added later), `.spectral.yaml`, the React app (`frontend/src/{api,auth,components,pages,lib}`), generated `schema.d.ts`, 59 Vitest tests (citation rendering, highlight-range mapping, SSE reducer), ESLint rule that forbids `fetch` outside `src/api`.
- **Human review:** *(owner to fill in)* contract field names, page flow, copy.
- **Verification:** Spectral lint clean; `npm run typecheck`, `lint`, `test`, `build` pass. Deviation: the frontend was built after the backend (so the contract could be checked against a running server). Deviation: the source viewer highlights the quote inside the chunk text, with no PDF page images.
- **New dependencies:** react-router, TanStack Query, openapi-typescript / openapi-fetch, Tailwind, Vitest + Testing Library (all from the plan); `react-router` was later moved to v7 after `npm audit`.

### 2026-10-20 - Phase 2: backend core, auth and access control

- **Goal:** FastAPI app factory, models, migrations, JWT auth, the single ACL function, upload validation, contract drift test.
- **AI produced:** `backend/app/**`, migration `0001`, `services/acl.py` (one decision function), uploads validated by magic bytes with a size cap and sha256 de-duplication, `tests/unit/test_contract.py`.
- **Human review:** *(owner to fill in)* **ACL rules and schema are the review priority.** Decision to confirm: workspace admins read every collection (documented in `docs/permissions.md`).
- **Verification:** unit tests, `alembic check` in the integration suite, drift test between FastAPI and `openapi.yaml`.
- **New dependencies beyond the plan list:** `pyjwt`, `bcrypt`, `python-multipart`, `pydantic-settings`, `asyncpg`, `pgvector`, `rapidfuzz` (quote matching), `prometheus-client`, `opentelemetry-*`, `testcontainers`.

### 2026-10-20 - Phase 3: ingestion

- **Goal:** worker, parsers, heading-aware chunker with exact offsets, PII scan, embedder interface, indexes.
- **AI produced:** Postgres jobs table with `FOR UPDATE SKIP LOCKED`, retries with backoff (10/20/40 s) and stuck-job recovery; PDF/DOCX/Markdown/HTML parsers; chunker; regex PII scan; FakeEmbedder (384-d feature hashing) and fastembed adapter; HNSW, GIN and btree indexes.
- **Bugs found by tests:** tsvector bulk insert failed with executemany (switched to ORM inserts); name shadowing in `detect`.
- **Verification:** parser fixtures, chunker offset tests, 8-worker no-double-claim test. Throughput recorded in `docs/rag-design.md`.

### 2026-10-20 - Phase 4: retrieval, generation and verification

- **AI produced:** vector + FTS search with the ACL filter in SQL, RRF (k=60), rerank 30 to 6, id-tagged source prompt with neutralised delimiters, structured claims, quote match (rapidfuzz, at least 0.9, at least 12 characters) and entailment, refusal policy, SSE stages, `/retrieval/explain`, per-stage latency.
- **Bugs found by tests:** a forged `<system>` tag passed through the prompt builder (fixed); an SSE test that matched a substring ("26") by accident (replaced with a parser helper).
- **Verification:** unit tests for the verifier modes (extractive, hallucinate, mismatch, obedient) and 6 injection tests.

### 2026-10-20 - Phase 5: evaluation

- **AI produced:** harness with personas and the metrics in `docs/eval-results.md`, experiment matrix, baseline regression gate (tolerance 0.02), quality UI and compare view, feedback-to-golden promotion, `rag-eval.yml`.
- **Bugs found by the harness's own checks:** nondeterministic tie-breaking, a worker stealing the evaluation's jobs, a persona crash in the member list. All fixed with regression tests.
- **Honest limits:** all numbers use the fake providers; the real-model run was **not executed**. The golden set was never edited to make a metric pass.
- **Deviation:** chunk-size experiment ran 64/128/default because demo pages are shorter than 256 tokens.

### 2026-10-20 - Phase 6: testing depth

- **AI produced:** 94 unit + 73 integration tests (17 ACL leak tests on every content endpoint), 6 prompt-injection tests, 9 Playwright E2E tests.
- **Verification:** all green at the end of the session; E2E 9/9 after a final rebuild.

### 2026-10-20 - Phase 7: containers and CI/CD

- **AI produced:** multi-stage Dockerfiles (non-root; `WITH_ML`, `WITH_S3` args), `docker-compose.yml`, `docker-compose.prod.yml`, Caddyfile, `ci.yml`, `rag-eval.yml`, `deploy.yml`, all actions pinned to commit SHAs.
- **Verification:** the stack was run and checked with `docker compose ps` and `/healthz`. **The workflows were not run on GitHub and nothing was deployed.** The owner decides on AWS (`docs/deployment.md`).
- **Human review:** *(owner to fill in)* every workflow, the production compose file and secrets handling. CI and deploy files are security-sensitive.

### 2026-10-20 - Phase 8: observability

- **AI produced:** Prometheus metrics, OTel tracing, Loki/Promtail, Tempo, Grafana dashboard, 8 alert rules (checked with `promtool`).
- **Verification:** targets up, rules loaded, traces received by Tempo, dashboard screenshot captured. The logs panel exposed a short dev JWT secret (fixed).

### 2026-10-20 - Phase 9: agent extension pack

- **AI produced:** 4 skills, 3 read-only subagents, MCP server (6 tools), 3 hooks + append-only check, plugin, nightly custom agent, `docs/permissions.md`, `docs/demo.md`.
- **Verification:** 60 hook tests, 12 MCP tests, 13 agent tests; live MCP check as a plain-member service user (restricted content invisible, `run_eval` returns 403).
- **Not recorded:** a live Claude Code session choosing the skill and spawning the subagent (marked "to rehearse" in the demo).
- **Bug found by tests:** the first guard failed open on an unusual path spelling (now matched by path tail).

### 2026-10-20 - Phase 10: security

- **AI produced:** scans (gitleaks, Semgrep, Trivy, pip-audit, npm audit) in `security/scan-results/`, `scan-summary.md`, `ai-pr-audit.md` (fix / accept / reject), threat model (16 threats), AI data policy.
- **Result:** Semgrep 35 to 1 (accepted, A10); Trivy fs clean after the nginx fix; manual review found 4 more issues (document text in DB errors, short dev secret, worker healthcheck, quotes left in stored answers), all fixed with tests.
- **Human review:** *(owner to fill in)* countersign `ai-pr-audit.md`. A review by the same agent that wrote the code is not independent.

### 2026-10-20 - Phase 11: docs and Substack

- **AI produced:** README, architecture, rag-design, eval-results, deployment docs, 14 Substack chapters, 12 generated figures, 12 screenshots of the running app.
- **Corrections made on review of its own text:** a fabricated anecdote in chapter 1 was removed; test counts and retry timings were checked against the code.
- **Not done:** demo video, public URL, publishing the series.


### 2026-10-21 - Stretch: EvalOps as the quality gate in CI

- **Goal:** send the per-question results of the golden-set run to EvalOps (project 1) and fail the build on its verdict. EvalOps could not accept results it had not computed itself, so the work spans both repositories: `POST /gate/ingest` there (see its `docs/ai-workflow.md`), the export, the publisher and the workflow here.
- **Human decision:** a hosted EvalOps (per-question regressions against the latest run on `main`) rather than an ephemeral one started in CI (absolute thresholds only).
- **AI produced:** `app/evals/evalops.py` (pass rule, stable `case_ref`, dataset export), `--cases-out` on the eval runner, `evals/publish_to_evalops.py` (stdlib, exit 0/1/2, bootstrap for the first `main` run), a gated step and a `push` trigger in `rag-eval.yml`, `docs/evalops-integration.md`, 21 tests.
- **Review:** an independent subagent reviewed the EvalOps contract before it was written. Two blocking findings (request size, unknown baseline label) were fixed before any code.
- **Bugs found by running it, not by reading it:** the output cap still used the pre-review 50000 instead of 5000 (a unit test caught it); `python -m app.evals.evalops` did nothing because the module had no `__main__` guard (only the real end-to-end run caught it, so a test now runs the documented command).
- **Verification:** real eval (fake providers, pgvector) into a real local EvalOps: first `main` run bootstraps and passes at 85 percent; an identical PR passes with 0 regressions; 4 degraded answers fail it (75 percent, 4 regressions) with exit code 1. **Not run on GitHub:** the workflow change itself, and the hosted setup (no hosted EvalOps exists yet).


### 2026-10-23 - Phase 12: private mode and public research

- **Goal (from the owner):** company documents must never leave the system, while published papers and any published web page stay searchable using the owner's Claude API key; deploy both projects for free with the EvalOps connection working.
- **Human decisions:** a hard reading of "never leaves" (so company text goes to a local model, and Claude only reads public text); keywords-only queries with a preview rather than a model rewriting the question; a separate private compose stack instead of changing the existing production one.
- **AI produced:** `egress/` (guard, the only HTTP client, the guard's view of the documents), `research/` (arXiv, Crossref, OpenAlex, Europe PMC, Semantic Scholar, web source), `LocalProvider`, `choose_llm` and `ensure_lane_safe`, boot-time private-mode checks, `scope`/preview/status in the API and UI, `docker-compose.private.yml` with a Squid allow-list proxy and Ollama, `deploy/verify-isolation.*`, redacted EvalOps export, EvalOps self-host compose with Tailscale Funnel and Cloudflare Tunnel profiles, metrics/alerts/panels, docs and chapter 15.
- **Verification:** 299 backend tests (was 188), 72 frontend (was 59), mypy strict and ruff clean. A canary planted in a company document appears in no outbound request and no hosted-model prompt in any scope. The proxy was run in both modes against real destinations (scholarly API 200; example.com, loopback, private ranges and the cloud metadata address refused). The whole private stack was built and started, `verify-isolation` passed all checks from inside the API container, and live questions went to arXiv, Crossref, OpenAlex and Europe PMC through the proxy. A real EvalOps was started from the new compose file and the redacted CiteSure results passed, passed against a baseline, and failed on a regression.
- **Design point decided before coding and covered by a test:** keywords are extracted from the question, so the derived query inherits the question's own blockers (personal data, secrets, deny terms); only two sentence-form reasons are ignored (`SOFT_REASONS`). Otherwise `jane.doe@acme.com` would reach a source as "jane doe acme com".
- **Mistakes caught by running the tests:** an assertion that a reason code did not contain the word "canary" (the code was right, the test was wrong); a web-source test whose page was too small to split into passages; an integration test that depended on other tests' document titles (the title rule did its job and blocked an ordinary word). All three were test errors, fixed in the tests.
- **Not done:** no real model was called (no key, no downloaded local model): the Claude public lane, the web source and the local model are covered by fakes and mock servers, so answer quality with Ollama and Claude is unmeasured. The Tailscale and Cloudflare containers were not started (they need accounts). No Playwright test of the public lane (needs live internet). Nothing was committed.


### 2026-10-26 - Fix Docker image CI scan

- **Goal:** fix the Docker images build job failing on a Trivy secret-scanner false positive in the installed Anthropic SDK documentation.
- **AI produced:** limited the Trivy image scan to vulnerability findings; the separate Gitleaks and filesystem secret scans remain unchanged.
- **Verification:** confirmed the Actions log reports masked placeholder strings from the SDK as a CRITICAL GCP service-account finding; validated the CI workflow and action pins locally.

### 2026-10-25 - Phase 5: audit log, dashboard, optional OIDC, vault and OCR

- **Goal (from the owner):** port the hardening features of document_explorer into CiteSure without making any of them a hard dependency: a tamper-evident audit log, an admin dashboard, optional OIDC sign-in, an encrypted file vault and local OCR.
- **Delegation:** the vault and OCR piece (independent files) went to a sub-agent with the same file-ownership rules; audit, dashboard and OIDC were written directly because they share `openapi.yaml`, `auth.py` and the route files.
- **Human decisions to confirm:** audit entries are scoped by workspace (plus the sign-ins of its members) and readable by workspace admins; OIDC never creates users unless `OIDC_AUTO_CREATE_USERS=true`; the identity provider is not on the egress allow-list and must be on the private network in private mode; `OIDC_REQUIRE_EMAIL_VERIFIED` can be turned off for Entra.
- **AI produced:** `models/security.py`, migration 0005 (hash-chain table with append-only triggers, OIDC identity and group-grant tables), `services/audit.py`, `services/oidc.py`, dashboard repository and service, admin routes, audit calls in the workspace, document, ask and evaluation routes, `AuditPage`, `DashboardPage` (inline SVG charts), the login button, `docs/audit-dashboard.md`, `docs/oidc.md`, `docs/vault-and-ocr.md`.
- **Verification:** unit and integration tests against a real Postgres, including tampering with and removing audit rows, 25 concurrent writers, a mocked identity provider (wrong nonce, audience, issuer, expiry, foreign key, `alg: none`, HS256 with the public key), and a check that no question, comment, file name or document word reaches the audit table. Not run: a real Keycloak, real Tesseract, a Docker build of the OCR image.
