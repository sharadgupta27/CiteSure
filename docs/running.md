# Running CiteSure: stacks, ports and build options

Every way to run CiteSure, which ports each stack opens, and the Docker build arguments. Quick start: [README](../README.md#run-it).

## Sample internal company

[examples/](../examples/README.md) holds the internal documents of an invented company, **Fernhollow Bicycle Works**: a handbook for everyone, engineering files for one group and finance files for another (Markdown, DOCX and PDF). The folder is laid out for the watched-folder inbox, so it imports without any uploading by hand. Set `INBOX_ROOT=/data/inbox`, `INBOX_HOST_DIR=./examples/inbox` and `INBOX_MOUNT_MODE=ro`, then run `docker compose run --rm api python -m app.seed_example` before `docker compose up -d`. Logins, setup steps and questions to try are in [examples/README.md](../examples/README.md).

## Docker files at a glance

| File | What it runs | Start | Published ports |
|---|---|---|---|
| [docker-compose.yml](../docker-compose.yml) | development stack, Docker project `citesure-dev`: db (pgvector), migrate, api, worker, frontend | `docker compose up -d --build` | 5173 (app), 8000 (API), 5432 (Postgres) |
| [docker-compose.private.yml](../docker-compose.private.yml) | private stack, project `citesure`: db, migrate, ollama, egress-proxy, api, worker, frontend, caddy; `ollama-pull` (profile `setup`, one-off model download) | `docker compose -f docker-compose.private.yml up -d --build` | `BIND_ADDRESS:HTTP_PORT` (default 127.0.0.1:8080) and `HTTPS_PORT` (8443), Caddy only |
| [docker-compose.gpu.yml](../docker-compose.gpu.yml) | overlay for the private stack: gives `ollama` an NVIDIA GPU | add `-f docker-compose.gpu.yml` | none |
| [docker-compose.prod.yml](../docker-compose.prod.yml) | one-VM production stack from GHCR images: db, migrate, api, worker, frontend, caddy | `docker compose -f docker-compose.prod.yml up -d` ([deployment.md](deployment.md)) | 80, 443 |
| [ops/docker-compose.observability.yml](../ops/docker-compose.observability.yml) | overlay for the development stack: Prometheus, Grafana, Tempo, OpenTelemetry Collector, Loki, Promtail | add `-f ops/docker-compose.observability.yml` | 3000 (Grafana), 9090 (Prometheus) |
| [ops/docker-compose.observability.private.yml](../ops/docker-compose.observability.private.yml) | overlay for the private stack: the same tools minus Promtail, on the no-internet network only | add `-f ops/docker-compose.observability.private.yml` | none (Grafana via Caddy at `/grafana/`) |
| [backend/Dockerfile](../backend/Dockerfile) | one image for api, worker, migrations and seed scripts (Python 3.12, non-root user) | built by the compose files | 8000 (inside the network) |
| [frontend/Dockerfile](../frontend/Dockerfile) | React build (Node 22) served by unprivileged nginx, which proxies `/api` | built by the compose files | 8080 (inside the network) |
| [deploy/egress/Dockerfile](../deploy/egress/Dockerfile) | the Squid allow-list proxy, the private stack's only way out | built by `docker-compose.private.yml` | 3128 (inside the network) |

Build arguments of `backend/Dockerfile`:

| Argument | Effect | Development stack | Private stack | Production images (CI) |
|---|---|---|---|---|
| `WITH_ML` | fastembed embeddings and cross-encoder reranker, models baked into the image | `false` (set `WITH_ML=true` to build them in) | `true` | `true` |
| `WITH_OCR`, `OCR_LANGS` | Tesseract for scanned PDFs (needs `OCR_ENABLED=true` at runtime) | not passed (no OCR build) | `false`, `eng` (set `WITH_OCR=true`) | not set |
| `WITH_S3` | boto3, for `STORAGE_BACKEND=s3` | not passed | not passed | `true` |

## Private mode and public research

CiteSure can run so that **company documents never leave your machine** while still answering from **published papers and web pages**.

| | |
|---|---|
| Company text | read only by a model you run (`LLM_PROVIDER=local`, e.g. Ollama) with local embeddings; a hosted model for it is refused at boot |
| Published research | arXiv, Crossref, OpenAlex, Europe PMC, Semantic Scholar (and, with your Claude key, any web page) through an **egress guard** and an **allow-list proxy**; only keywords go out, you can preview and edit them, and every answer says what was sent |
| Claude or OpenAI | reads public passages and guard-cleared questions only; never company text. Needs `PUBLIC_LLM_PROVIDER=anthropic` or `openai` and API credit; with `none`, the local model reads public passages too. The `web` source needs Claude (it uses Claude's web search) |
| Proof | a canary planted in a document never appears in any outbound request or hosted prompt (integration tests); `deploy/verify-isolation.sh` proves the running stack has no other route out |

```bash
cp .env.private.example .env       # secrets, EGRESS_DENY_TERMS, optionally ANTHROPIC_API_KEY or OPENAI_API_KEY for the public lane
docker compose -f docker-compose.private.yml --profile setup run --rm ollama-pull
docker compose -f docker-compose.private.yml up -d --build && deploy/verify-isolation.sh
```

With an NVIDIA GPU, add `-f docker-compose.gpu.yml` to the `up` command (needs the NVIDIA Container Toolkit, or Docker Desktop with the WSL2 GPU backend). On a CPU-only machine, raise `LOCAL_LLM_TIMEOUT_S` if answers fail with "The local model failed".

Keeping the private settings in a separate file (for example `.env.private`) instead? Compose reads only `.env` by itself, so add `--env-file .env.private` to every `docker compose -f docker-compose.private.yml ...` command above.

[docs/public-research.md](public-research.md) · [docs/private-deployment.md](private-deployment.md) · [docs/free-deployment.md](free-deployment.md) (free hosting, and how EvalOps stays connected) · [docs/evalops-integration.md](evalops-integration.md)

## Where to open everything

Each stack publishes different ports. Links work once that stack is running. The development stack (Docker project `citesure-dev`) and the private stack (project `citesure`) have separate containers, volumes and ports, so they can run side by side, and the development stack never opens the private database.

**Development stack** (`docker compose up -d --build`):

| Web app | Link | Notes |
|---|---|---|
| CiteSure app | [http://localhost:5173](http://localhost:5173) | sign in with a demo user (see the [README](../README.md#run-it)) |
| API docs (Swagger UI) | [http://localhost:8000/docs](http://localhost:8000/docs) | interactive; switched off when `ENV=prod` |
| API OpenAPI schema | [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json) | generated by FastAPI; the contract is [openapi.yaml](../openapi.yaml) |
| API health | [http://localhost:8000/healthz](http://localhost:8000/healthz) | |
| API metrics (Prometheus format) | [http://localhost:8000/metrics](http://localhost:8000/metrics) | |

**Observability overlay for the development stack** (`docker compose -f docker-compose.yml -f ops/docker-compose.observability.yml up -d --build`):

| Web app | Link | Notes |
|---|---|---|
| Grafana (dashboards, traces, logs) | [http://localhost:3000](http://localhost:3000) | `admin` / `admin` on first start; change it |
| Prometheus (metrics, alerts) | [http://localhost:9090](http://localhost:9090) | |

**Private stack** (`docker compose -f docker-compose.private.yml up -d`). Everything goes through Caddy on `BIND_ADDRESS:HTTP_PORT`, which defaults to `127.0.0.1:8080`:

| Web app | Link | Notes |
|---|---|---|
| CiteSure app | [http://127.0.0.1:8080](http://127.0.0.1:8080) | change `HTTP_PORT` if 8080 is taken |
| Ask | [http://127.0.0.1:8080/ask](http://127.0.0.1:8080/ask) | every user |
| Documents | [http://127.0.0.1:8080/documents](http://127.0.0.1:8080/documents) | every user |
| Learn (summaries, comparisons, study sets, plans) | [http://127.0.0.1:8080/learn](http://127.0.0.1:8080/learn) | every user |
| Dashboard | [http://127.0.0.1:8080/dashboard](http://127.0.0.1:8080/dashboard) | workspace admins |
| Audit log | [http://127.0.0.1:8080/audit](http://127.0.0.1:8080/audit) | workspace admins |
| Inbox (watched folder) | [http://127.0.0.1:8080/inbox](http://127.0.0.1:8080/inbox) | workspace admins |
| Workspace (members, groups, collections) | [http://127.0.0.1:8080/workspace](http://127.0.0.1:8080/workspace) | workspace admins |
| Feedback queue | [http://127.0.0.1:8080/feedback](http://127.0.0.1:8080/feedback) | workspace admins |
| Quality (evaluation runs) | [http://127.0.0.1:8080/quality](http://127.0.0.1:8080/quality) | workspace admins |
| Health | [http://127.0.0.1:8080/healthz](http://127.0.0.1:8080/healthz) | |
| Grafana (dashboards, traces) | [http://127.0.0.1:8080/grafana/](http://127.0.0.1:8080/grafana/) | only with the private observability overlay (below); user `admin`, password `GRAFANA_ADMIN_PASSWORD`. Without the overlay this link gives 502 |

The same pages also exist on the development stack at `http://localhost:5173/<page>`. In the private stack the API docs are off (it runs with `ENV=prod`), and Caddy answers `/metrics` with 404 so metrics never leave the machine. HTTPS on `HTTPS_PORT` (default 8443) works only after you set `SITE_ADDRESS` to a real domain name; with the default `:80` the stack serves plain HTTP on this machine only.

Private observability overlay: `docker compose -f docker-compose.private.yml -f ops/docker-compose.observability.private.yml --env-file .env.private up -d`. Prometheus, Loki, Tempo, the collector and Grafana join only the no-internet network and publish no ports; Grafana is reached through Caddy. Promtail is left out because it needs the Docker socket, so the dashboard's log panel is empty there (use `docker compose logs api`). Details: [docs/private-deployment.md](private-deployment.md#monitoring).

**Production stack** ([docker-compose.prod.yml](../docker-compose.prod.yml)): `https://<DOMAIN>` (Caddy gets the certificate automatically). It isn't deployed; see [deployment.md](deployment.md).

The MCP server ([mcp-server/](../mcp-server/)) is not a web app. It runs as a stdio server inside your agent client.

