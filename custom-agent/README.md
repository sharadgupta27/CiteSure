# Custom agent: the nightly regression watcher

**Why a custom agent and not an interactive coding agent?** This job runs unattended on a schedule, must be reproducible, must have
tiny permissions, and has one output (a GitHub issue). An interactive agent adds cost, randomness and a large permission surface for no benefit.
(See `docs/agent-extension-pack.md`, "When to build a custom agent".)

## What it does

```text
nightly workflow ─▶ real-model evaluation ─▶ eval-results.json
                                                │
                        agent.py ◀──────────────┘   + previous night's results
                          │
        compare metrics (tolerance 0.02; restricted refusals must be 1.00)
                          │
        suspects by metric pattern  (+ per-question evidence with --api)
                          │
              one GitHub issue (or a comment on the open one)
```

- Reads: the two JSON result files; optionally a running CiteSure (as a service user) for per-question evidence.
- Writes: **only** a GitHub issue/comment, labelled `rag-regression`. It never edits code, data or the golden set.
- Permissions: `issues: write` for the workflow token; a plain CiteSure account if `--api` is used. See `docs/permissions.md`.

## Run it

```bash
cd backend
uv run python -m app.evals.run --matrix evals/experiments.yaml --out eval-results.json
python ../custom-agent/agent.py --results eval-results.json --previous evals/last-nightly.json --config hybrid+rerank --dry-run
# in CI: add --open-issue (needs GITHUB_TOKEN and GITHUB_REPOSITORY)
```

Tests (no network): `cd custom-agent && uv run --no-project --with pytest --with httpx python -m pytest -q`

## Extending it

It is intentionally rule-based. If you later add an LLM step ("explain the likely root cause from these diffs"), keep these rules:
give it **no tools**, pass results as data inside delimiters, and keep the issue as the only side effect.
