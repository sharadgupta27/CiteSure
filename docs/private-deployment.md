# Private deployment: company documents never leave the system

The promise: **no company document, chunk, embedding, or company question is sent to a hosted model or to the public internet.** Published research still comes in, through one narrow door ([public-research.md](public-research.md)).

## How the promise is built (four layers, each enough to stop a leak on its own)

| Layer | What it does | Where | Proof |
|---|---|---|---|
| 1. Models | company text is read only by `LLM_PROVIDER=local` (Ollama, vLLM, llama.cpp...) and local embeddings/reranker | `llm/local_provider.py`, `fastembed` | `test_local_llm_and_modes.py` |
| 2. Boot checks | `PRIVATE_MODE=true` refuses to start with a hosted internal model, Voyage embeddings, a "local" URL on a public address, or (in prod) no egress proxy | `config.assert_private_mode_consistent` | `test_private_mode_*` |
| 3. Routing | `choose_llm` gives company text only to the internal model; `ensure_lane_safe` raises `PrivacyViolation` otherwise | `services/pipeline.py` | `test_the_safety_net_*`, `test_public_research.py` |
| 4. Network | the API, worker, database and model server sit on a Docker network with **no route to the internet**; the only way out is a proxy that allows named hosts and refuses private addresses | `docker-compose.private.yml`, `deploy/egress/` | `deploy/verify-isolation.sh`, `test_deploy_config.py`, the `private-stack` CI job |

Layers 1-3 are code and could contain a bug. Layer 4 does not depend on that code: even a compromised API container cannot open a connection to the internet.

```text
                ┌────────────────────────── internal network (no route out) ──────────────────────────┐
browser ─▶ caddy│─▶ frontend ─▶ api ─▶ db            api ─▶ ollama (local model)       worker ─▶ db    │
   (127.0.0.1)  │                 │                                                                    │
                │                 └─▶ egress-proxy ─────────────────────────────────────┐              │
                └───────────────────────────────────────────────────────────────────────│──────────────┘
                                                                          edge network: │ allow-listed HTTPS only
                                                                                        ▼ arXiv, Crossref, OpenAlex, Europe PMC, (Anthropic)
```

## What you need

| | Minimum | Comfortable |
|---|---|---|
| Machine | 8 GB RAM, 4 cores, 15 GB disk | 16 GB RAM, or an NVIDIA GPU with 6+ GB VRAM |
| Software | Docker Desktop (Windows/macOS) or Docker Engine | the same, plus the NVIDIA container toolkit for the GPU overlay |
| Model | `llama3.2:3b` (about 2 GB; usable on CPU) | a larger model on a GPU, same configuration |

Local models answer more slowly and less well than Claude. The default is deliberately small. Measure with your own questions (`docs/eval-results.md` shows how) and pick the model on the evidence; changing it is two lines in `.env`.

### Choosing a smaller or larger local model

Sizes are approximate downloads; none of these were measured on CiteSure's golden set yet, so treat the order as a starting guess, not a result.

| `LOCAL_ANSWER_MODEL` / `LOCAL_VERIFY_MODEL` | Size | Notes |
|---|---|---|
| `llama3.2:1b` | ~1.3 GB | fastest; expect weak citations and many refusals |
| `qwen2.5:1.5b` | ~1 GB | small and good at following format instructions (Apache 2.0) |
| `llama3.2:3b` (default) | ~2 GB | a reasonable floor for grounded answers on CPU |
| `phi4-mini` | ~2.5 GB | 3.8B, strong reasoning for its size (MIT) |
| `gemma3:4b` | ~3 GB | good general quality |

Check each model's licence before using it at work. Avoid "thinking" models (for example `qwen3`) as the verifier unless you disable thinking: they spend many seconds reasoning before every short answer.

The verifier decides which claims are dropped, so a model too weak to judge makes the system either drop true claims or keep unsupported ones. Run the evaluation with `LLM_PROVIDER=local` and compare `faithfulness` and `citation precision` against the numbers in `docs/eval-results.md` before relying on a model. After changing the model, run the `ollama-pull` step again.

## Setup (about 30 minutes, most of it downloads)

```bash
cp .env.private.example .env          # fill in POSTGRES_PASSWORD, JWT_SECRET, SEED_PASSWORD; set EGRESS_DENY_TERMS
docker compose -f docker-compose.private.yml --profile setup run --rm ollama-pull   # once: downloads the model(s)
docker compose -f docker-compose.private.yml up -d --build                           # builds with local embeddings baked in
docker compose -f docker-compose.private.yml run --rm api python -m app.seed         # optional demo company
deploy/verify-isolation.sh                                                           # Windows: deploy\verify-isolation.ps1
```

Open `http://localhost:8080`. The port is bound to `127.0.0.1`. To reach it from other devices, do **not** set `BIND_ADDRESS=0.0.0.0` on a laptop; put Tailscale or Cloudflare Access in front of it (see [free-deployment.md](free-deployment.md)), then set `SITE_ADDRESS` to your hostname for automatic HTTPS.

`verify-isolation` runs inside the API container and proves: raw sockets and DNS to the internet fail; the proxy is configured; an allow-listed host is reachable through it; a host outside the list, the cloud metadata address and private ranges are refused; the local model is reachable and the answer model is downloaded; the settings pass the private-mode check. It is the thing to run after every change to the compose file.

### Turning the public lane on and off

- Off completely: `PUBLIC_RESEARCH_ENABLED=false`. The API never makes an outbound request, the proxy is idle, and you can also remove the `edge` network from `egress-proxy` for a hard guarantee.
- Scholarly sources only (default): `PUBLIC_SOURCES=arxiv,crossref,openalex,europepmc`.
- With Claude for public text (your API key): `PUBLIC_LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=...`. Claude then answers public-only questions that passed the guard. Add `web` to `PUBLIC_SOURCES` and set `EGRESS_MODE=open` for arbitrary published pages.

## Operating it

| Task | How |
|---|---|
| Change the model | edit `LOCAL_ANSWER_MODEL`, run `ollama-pull`, `up -d`; run the evaluation (`uv run python -m app.evals.run --matrix evals/experiments.yaml` from `backend/` with `LLM_PROVIDER=local`) and record the numbers in `docs/eval-results.md` |
| Add a source host | add it to `deploy/egress/allowlist.txt` **and** `EGRESS_ALLOW_HOSTS`; `test_deploy_config.py` fails if they differ |
| See what left | Grafana "Public lane" panel, `egress` on every answer, `docker compose logs egress-proxy` (one line per connection, hosts only) |
| Back up | the `pgdata` and `uploads` volumes; the `ollama` volume is re-downloadable |
| Update | `git pull && docker compose -f docker-compose.private.yml up -d --build`; migrations run first |
| Rotate secrets | change `.env`, `up -d`; changing `JWT_SECRET` signs everyone out |

## What private mode does not cover

- **People and tools next to the system**: a coding agent that reads chunks through the MCP server sends them to its vendor (the MCP `ask` tool is pinned to the internal scope so it never searches the public web, but its output is still read by the agent's model). Keep agents on the fictional corpus. See [security/ai-data-policy.md](../security/ai-data-policy.md).
- **Backups and the host**: disk encryption and who can read the Docker volumes are your responsibility.
- **EvalOps**: see below.
- **Topics in keywords** when the public lane is on ([public-research.md](public-research.md#limits-you-should-know)).

## EvalOps and private data

CiteSure's CI sends EvalOps one record per golden question: a hash key, pass or fail, a score, a latency and a short output. The shipped golden set and the CI run use the fictional corpus. For a real corpus set `PRIVATE_MODE=true` (or pass `--redact`): the dataset export replaces question and reference-answer text with `[redacted]`, and the results carry `[answered]` or `[refused]` instead of answer text, so EvalOps keeps its history and its gate while the words stay here. Verified against a live EvalOps: it stored 40 cases with `[redacted]` inputs and `[answered]`/`[refused]` outputs and still passed, passed against a baseline, and failed on a regression. Do not run EvalOps' own real-model evaluators over real company questions unless you accept that they go to the evaluator's provider.
