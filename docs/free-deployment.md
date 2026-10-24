# Deploying CiteSure and EvalOps for free, with the connection intact

The connection is one HTTPS call: CiteSure's CI sends `POST /api/v1/gate/ingest` to EvalOps with a project API key. So the only requirement is **that call can reach EvalOps**. Everything else is a choice of where each project runs.

```text
 your machine (or a free VM)                                        GitHub
┌──────────────────────────────────────────────┐        ┌──────────────────────────┐
│ CiteSure private stack   (never exposed)     │        │ CiteSure repo, rag-eval  │
│   documents, local model, Postgres           │        │   fake providers,        │
│                                              │        │   fictional corpus       │
│ EvalOps self-host stack                      │◀──────│   POST /gate/ingest      │
│   Postgres, API, UI                          │ tunnel │   (verdict: pass / fail) │
└──────────────────────────────────────────────┘        └──────────────────────────┘
```

CiteSure holds your documents, so it is **never** published. EvalOps holds only evaluation history, so it can be.

## Pick a layout

| Layout | Cost | EvalOps URL stable? | CI reaches EvalOps | Best for |
|---|---|---|---|---|
| **A. Everything on your machine, self-hosted runner** | free | not needed | the runner is on the same machine: `http://localhost:8000` | real private use; nothing is exposed at all |
| **B. Your machine + Tailscale Funnel** | free | yes (`https://evalops.<tailnet>.ts.net`) | GitHub-hosted runners via the public Funnel URL | normal GitHub CI, no domain |
| **C. Your machine + Cloudflare Tunnel** | free tunnel, but you need a domain on Cloudflare (about 10 USD/year) | yes | GitHub-hosted runners | you already own a domain |
| **D. Always-on free VM (Oracle Cloud Always Free)** | free (card for sign-up; the Arm tier is 2 OCPU / 12 GB since June 2026 and idle instances can be reclaimed) | yes, with a domain or an IP | GitHub-hosted runners | EvalOps and a fake-provider CiteSure demo running while your laptop is off |

A free VM cannot hold the local model (12 GB is too small for a useful one) and should not hold real documents. Use D for the **public demo** (fake providers, fictional corpus), A or B for **real use**.

Not recommended for always-on use: Render's free tier sleeps after 15 idle minutes (the gate would time out) and its free Postgres expires after 30 days; Fly.io has no permanent free allowance. Prices and limits change; check the provider's page before relying on them.

## Layout B step by step

Everything below was run locally (the EvalOps stack, the dataset import, the gate passing, passing against a baseline and failing on a regression) except the two tunnel containers, which need your Tailscale or Cloudflare account.

### 1. EvalOps

```bash
cd EvalOps
cp .env.selfhost.example .env.selfhost       # POSTGRES_PASSWORD, JWT_SECRET, TS_AUTHKEY, TS_HOSTNAME=evalops
docker compose --env-file .env.selfhost -f docker-compose.selfhost.yml --profile funnel up -d --build
```

`TS_AUTHKEY`: a reusable auth key from the Tailscale admin console. Enable HTTPS certificates and Funnel for your tailnet once (see Tailscale's Funnel documentation). The URL is `https://evalops.<tailnet>.ts.net`. Set `PUBLIC_URL` to it in `.env.selfhost` so CORS allows the UI.

Layout C instead: create a tunnel in Cloudflare Zero Trust, route a hostname to `http://frontend:8080`, put the token in `TUNNEL_TOKEN`, and use `--profile tunnel`. Protect the UI (not `/api/v1/gate/*`) with a Cloudflare Access rule for your email.

### 2. Create the project, dataset and key (once)

1. Open EvalOps, register, create a project.
2. Export CiteSure's golden set as a dataset and import it (Datasets, Import). For real data add `PRIVATE_MODE=true` so the file carries `[redacted]` instead of questions:

   ```bash
   cd CiteSure/backend && uv run python -m app.evals.evalops --export-dataset eval-dataset.jsonl
   ```
3. Create a project API key (shown once) and set the gate policy (minimum pass rate, allowed regressions).

### 3. Tell CiteSure's CI

GitHub, CiteSure repository, Settings, Secrets and variables, Actions:

| Name | Kind | Value |
|---|---|---|
| `EVALOPS_URL` | secret | `https://evalops.<tailnet>.ts.net` (no trailing slash) |
| `EVALOPS_API_KEY` | secret | the project key (`eo_...`) |
| `EVALOPS_DATASET_ID` | variable | the dataset's id |

Push to `main`: the first run bootstraps the `main` baseline; later pull requests are compared with it. Details and failure modes: [evalops-integration.md](evalops-integration.md). If EvalOps is unreachable the step exits 2 and the job fails on purpose; with the secrets unset (forks) it is skipped.

### 4. CiteSure, privately

Follow [private-deployment.md](private-deployment.md). Nothing about it depends on EvalOps being reachable.

## Layout A: a self-hosted runner instead of a tunnel

If the CiteSure repository is **private**, run the GitHub Actions runner on the same machine as EvalOps (Settings, Actions, Runners, New self-hosted runner). Point `EVALOPS_URL` at `http://localhost:8000` (the self-host compose publishes the API on `127.0.0.1:8000`) and change the `rag-eval.yml` job to `runs-on: [self-hosted, linux]` (the job starts a Postgres service container, so the runner needs Docker on Linux or WSL). Nothing is exposed to the internet. Do not use self-hosted runners with public repositories: a pull request from a stranger would run on your machine.

## Layout D: an always-free VM for the public demo

1. Create an Oracle Cloud Always Free Arm VM (Ubuntu), open ports 80 and 443 only, install Docker.
2. EvalOps: copy `EvalOps/` to the VM, use `docker-compose.selfhost.yml` with `--profile tunnel` or Caddy from `docker-compose.prod.yml` and a domain (the repository's `deploy.yml` automates this; see `EvalOps/docs/deployment.md`).
3. CiteSure demo: `docker-compose.prod.yml` with `LLM_PROVIDER=fake`, `EMBEDDING_PROVIDER=fastembed` and no real documents (`docs/deployment.md`).
4. Put the demo URLs in each README and record a screenshot: that completes the "deployed" rubric items.

## What each part sends to whom

| Component | Sends | To | Contains company text? |
|---|---|---|---|
| CiteSure private stack | keywords (guarded) | arXiv, Crossref, OpenAlex, Europe PMC; with `web`, Anthropic and public pages | no |
| CiteSure private stack | public passages and cleared questions | Anthropic (your API key), only if `PUBLIC_LLM_PROVIDER=anthropic` | no |
| CiteSure CI | per-question pass/fail, score, latency, short output | EvalOps | no: fictional corpus in CI; redacted in private mode |
| EvalOps | nothing | | with `LLM_PROVIDER=fake`; with `anthropic`, the cases you run go to Anthropic |

## Costs you may still have

Your Anthropic API usage (public-only answers, web search at Anthropic's per-search price, EvalOps real-model runs); electricity for the machine; a domain only for layout C. The spend guards (`MAX_COST_PER_RUN_USD`, `MAX_DAILY_COST_USD` in EvalOps; `LlmSpendHigh` and the egress alerts in CiteSure) bound a mistake.
