# Architecture

## The big picture

```text
                         ┌─────────────────────────────── FastAPI (api) ──────────────────────────────────┐
┌──────────────┐  REST   │  /ask ─▶ pipeline                                                              │
│ React (Vite) │────────▶│    1. ACL: which collections may this user read?                               │
│  frontend/   │◀──SSE───│    2. hybrid retrieve: pgvector top-k ∪ Postgres full-text top-k (both ACL-    │
└──────────────┘         │       filtered inside the SQL)  3. fuse (RRF)  4. rerank                       │
   nginx :5173           │    5. generate claims + quotes  6. verify (quote match + entailment)            │
        │                │    7. keep verified claims, or refuse                                          │
        ▼                │  /documents ─▶ validate, store blob, enqueue ingestion job                      │
 proxies /api ──────────▶└───────────────┬────────────────────────────────────────────────────────────────┘
                                         │                          ┌──────────────────────────┐
                                         ▼                          │ Postgres 16 + pgvector   │
                         ┌────────────────────────────┐             │ users, workspaces, ACLs, │
                         │ Worker (same image)        │◀───────────▶│ documents, chunks        │
                         │ parse → chunk → PII scan → │             │ (vector + tsvector),     │
                         │ embed → index; eval runs   │             │ jobs, answers, feedback, │
                         └────────────────────────────┘             │ golden set, eval runs    │
                                                                    └──────────────────────────┘
   Providers behind interfaces:  LLMProvider (Local | Anthropic | Fake)    Embedder (fastembed | Voyage | Fake)
                                 Reranker (cross-encoder | lexical | none)    BlobStore (local | S3)
```

## How the pieces fit (the rubric's "technologies and how they connect")

| Layer | Technology | Role |
|---|---|---|
| Frontend | React 18, TypeScript (strict), Vite, Tailwind, TanStack Query, React Router, `openapi-fetch` | The UI. All HTTP goes through `src/api/` (typed client generated from `openapi.yaml`; SSE in `stream.ts`). Served by nginx, which also proxies `/api` to the API (no CORS in production). |
| API contract | `openapi.yaml` (OpenAPI 3.1), Spectral | Source of truth. The TS client is generated from it; `tests/unit/test_contract.py` fails if FastAPI drifts. |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic | Layered `api → services → repositories`. Routers only parse and call services; services never import FastAPI; all SQL lives in repositories and `rag/retrieval`. |
| RAG core | `app/rag/{parsing,chunking,retrieval,generation,verification}` | Pure, swappable stages with typed inputs and outputs. |
| Database | PostgreSQL 16 + pgvector (HNSW index) + full-text (GIN index) | Documents, chunks (embedding + `tsvector`), ACLs, jobs, answers, feedback, evaluation. One database for everything. |
| Background work | A `jobs` table polled with `FOR UPDATE SKIP LOCKED` | Ingestion, reindexing and evaluation run in the worker, never in a request handler. |
| LLM | `LLMProvider`: a local model (`LocalProvider`, any OpenAI-compatible server) for company text, the Anthropic SDK (`ANSWER_MODEL`, `VERIFY_MODEL`) for public text or non-private setups | Structured outputs (JSON schema) for claims and verdicts. A deterministic fake is the default for dev and tests. |
| Embeddings | `fastembed` ONNX locally (default); Voyage optional | 384-dimension vectors. |
| Containers | Docker, Docker Compose (`api`, `worker`, `frontend`, `db`, one-shot `migrate`) | One command runs everything. Multi-stage images, non-root user, health checks. |
| CI/CD | GitHub Actions | `ci.yml` (lint, types, unit, integration, E2E, security scans, image build), `rag-eval.yml` (quality gate), `deploy.yml` (GHCR + EC2 after green CI). |
| Deployment | AWS EC2 (t3.medium) + Docker Compose + Caddy (automatic HTTPS); S3 optional for uploads | Single VM, one Postgres, local embeddings. |
| Observability | OpenTelemetry → Tempo, Prometheus, Loki, Grafana | Per-stage latency, refusal and verification-drop rates, cost, queue depth; alerts. |
| Security | gitleaks, Semgrep, Trivy, pip-audit, npm audit; regex PII scan; threat model | See `security/`. |

## Request flow: `POST /ask`

1. Authenticate (JWT) → `acl.context_for_workspace` → the list of collection ids the user may read (admins: all; members: open collections + collections of their groups).
2. Embed the question → vector search and full-text search, both `WHERE collection_id IN (allowed)`; fuse with Reciprocal Rank Fusion; rerank the top 30 to the top 6.
3. Build the prompt: system prompt (versioned file) + `<source id="S1" …>` blocks (document text neutralised so it cannot close the tags) + the question.
4. The model returns JSON: `claims[]`, each with `citations[{source_id, quote}]`.
5. Verify every claim: the quote must be found in the cited chunk (fuzzy, ≥ 0.9), then a cheaper model must judge the claim `supported` by the evidence window. Others are dropped.
6. If any claim survives → `answered` with real chunk ids and quote offsets; else `refused` with the closest readable documents.
7. Persist the answer (config snapshot, per-stage latency, tokens, cost); stream `stage` events during, `token` events after verification, then `final`.

## Two lanes: company documents and published research

`POST /ask` takes a `scope`: `internal` (default), `public` or `both`. Details: [public-research.md](public-research.md); deployment: [private-deployment.md](private-deployment.md).

```text
question ─▶ internal lane: ACL ─▶ hybrid retrieve ─▶ rerank ──────────────┐
        │                                                                  ├─▶ sources S1..Sn ─▶ choose_llm ─▶ generate ─▶ verify ─▶ answer
        └─▶ public lane: egress guard ─▶ keywords ─▶ guard ─▶ EgressClient ─┘          │
                          (question)      (<= 8 words)      │  arXiv, Crossref, OpenAlex, Europe PMC, web
                                                            ▼
                                               allow-list proxy (the only route out)
choose_llm: any company text  ─▶ internal model (local in private mode)
            public text only + question cleared by the guard ─▶ public model (Claude)
```

| Piece | File |
|---|---|
| Scope, routing, the safety net | `services/pipeline.py` (`choose_llm`, `ensure_lane_safe`) |
| What may leave | `egress/guard.py`; the guard's view of the documents `egress/corpus.py` |
| The only way out | `egress/client.py` (https only, allow-list or public-only, SSRF checks, size cap, redirects re-validated) |
| Sources | `research/connectors.py` (parsers are pure functions), `research/web.py`, orchestration `research/service.py` |
| Local model | `llm/local_provider.py` (any OpenAI-compatible server: Ollama, vLLM, llama.cpp) |
| Boot-time guarantees | `config.py: assert_private_mode_consistent` |
| Network guarantees | `docker-compose.private.yml`, `deploy/egress/` |

Public passages are `ScoredChunk`s with `source_type="public"` and a `url`, so the existing generation and verification stages work unchanged; they have no database row, so stored answers keep their public citations without an ACL re-check.

## Request flow: upload

`POST /collections/{id}/documents` (admin) → size cap → **magic-byte** type detection → sha256 duplicate check → store blob → insert `documents` row (`queued`) + `jobs` row → `202`.
The worker claims the job, parses (`parsing`), chunks and embeds (`embedding`), swaps the chunks in one transaction and sets `ready`. Unparseable files end as `failed` with a readable reason and are not retried; transient errors retry with backoff.

## Data model (summary)

`users`, `workspaces`, `memberships(role)`, `groups`, `group_members`, `collections(visibility)`, `collection_groups` (who may read) → `documents(status, sha256, blob_key)` → `chunks(text, heading_path, page_*, char_*, embedding VECTOR(384), tsv, pii_flags)`;
`jobs`; `threads`, `answers(answer_json, config_snapshot, latency_ms_by_stage, cost)`, `feedback`; `golden_questions`, `eval_runs`, `eval_items`.
Chunks store `collection_id` (denormalised) so the ACL filter and the vector search run in one SQL statement. Full DDL: `backend/migrations/versions/`.

## Environments and the database (config, rubric 7)

| | dev | test | prod |
|---|---|---|---|
| Database | Compose `db` (pgvector image), port 5432 | testcontainers (a throw-away `pgvector/pgvector:pg16` per test session, real Alembic migrations) | Compose `db` on the VM, internal network only, volume `pgdata` |
| `ENV` | `dev` | `test` | `prod` (refuses a dev JWT secret or `*` CORS; hides `/docs`) |
| Providers | fake by default | fake always | `LLM_PROVIDER=anthropic`, `EMBEDDING_PROVIDER=fastembed`, `RERANKER=cross-encoder` |
| Uploads | local volume | temp dir | local volume or S3; `UPLOADS_ENABLED=false` for the public demo |
| Migrations | `docker compose run --rm migrate` runs on `up` | applied in the fixture | `docker compose run --rm migrate` in the deploy step |

All settings are environment variables documented in `.env.example` and parsed by `backend/app/config.py`. `DATABASE_URL` is the only database setting; Alembic and the app read the same one.
Never edit an applied migration; create a new one (`uv run alembic revision --autogenerate -m "..."`). `alembic check` runs in the tests and fails if models and migrations disagree.

## Repository layout

```text
backend/app/{api,services,repositories,rag,llm,embeddings,egress,research,storage,worker,evals}   backend/{migrations,tests,evals}
frontend/src/{api,auth,components,pages,lib}       e2e/        corpus/        openapi.yaml
docker-compose.yml  docker-compose.prod.yml  docker-compose.private.yml  deploy/{Caddyfile,Caddyfile.private,egress/,verify-isolation.*}  ops/  security/  docs/
agent-capabilities/ agent-hooks/ mcp-server/ plugins/ custom-agent/   substack/
```

## Operations

**Run:** `docker compose up -d --build`, then `docker compose run --rm api python -m app.seed`. Add monitoring: `docker compose -f docker-compose.yml -f ops/docker-compose.observability.yml up -d` (Grafana `:3000`, Prometheus `:9090`).

**Runbook for the alerts** (`ops/prometheus/alerts.yml`):

| Alert | First checks |
|---|---|
| `RefusalRateSpike` | Did a reindex or an embedding change run? `curl /api/v1/retrieval/explain` for a known question. Run `python -m app.evals.run`. Did access rules or collections change? |
| `VerificationDropRateSpike` | Did `ANSWER_MODEL` or a prompt change? Are quotes failing because parsing changed whitespace? Check `dropped_claims` in recent answers. |
| `IngestionBacklog` / `WorkerDown` | `docker compose logs worker`; failing jobs retry with backoff and show `error` in the `jobs` table; a crashed worker's job is re-claimed after 15 minutes. |
| `ServerErrors` / `ApiDown` | `docker compose logs api`; `/healthz` reports database connectivity. |
| `LlmSpendHigh` | Look for one user in `answers` (rate limit is 30/min per user); lower `RATE_LIMIT_ASK_PER_MIN` or the model. |

**Backups:** the Postgres volume `pgdata` and the uploads volume (or S3 bucket). Restore = restore both, then `alembic upgrade head`. **Reindex everything:** `POST /documents/{id}/reindex` per document (after changing the chunker or embedding model).
**Rotate secrets:** change `JWT_SECRET` and restart the API (everyone signs in again).
