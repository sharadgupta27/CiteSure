# EvalOps as CiteSure's quality gate

CiteSure's evaluation measures retrieval and answer quality. [EvalOps](https://github.com/sharadgupta27/EvalOps) (project 1) keeps the history of those runs and decides whether a change may merge. This page explains how the two are connected and how to set it up.

## How it works

```text
PR or push to main
  └─ rag-eval.yml (fake LLM + embedder, deterministic)
       ├─ python -m app.evals.run ... --cases-out eval-cases.json     one result per golden question
       ├─ evals/check_regression.py                                     committed baseline (aggregate metrics)
       └─ evals/publish_to_evalops.py ──► POST /api/v1/gate/ingest ──► EvalOps
                                                                        records a run, compares it with the
                                                                        latest run labelled `main`, answers
                                                                        pass or fail with the reasons
```

The two checks complement each other. `check_regression.py` compares **aggregate metrics** (recall, MRR, faithfulness, ...) with `evals/baseline.json`. EvalOps compares **question by question**: it names the exact questions that got worse, so a change that fixes three questions and breaks three others, leaving the averages unchanged, still fails.

EvalOps never runs CiteSure's pipeline or calls a model. CiteSure computes the results and EvalOps stores them, which is why it needs a dedicated endpoint (`POST /gate/ingest`) instead of `POST /gate`.

## When does a question pass?

Defined in `backend/app/evals/evalops.py`:

| Question | Passes when |
|---|---|
| Answerable | it was answered, the expected source was retrieved, and the judge scored the answer at least 0.5 |
| Unanswerable or restricted | it was refused |

The per-question score is the judge's correctness for answerable questions, and 1 or 0 for refusals. The thresholds that turn this into a verdict (minimum pass rate, allowed regressions) are EvalOps' **gate policy** for the project and are set there, not here.

## One-time setup

1. **Run EvalOps** somewhere CI can reach. Create a project and a user.
2. **Export the golden set as a dataset** and import it into a new EvalOps dataset (Datasets, Import):

   ```bash
   cd backend
   uv run python -m app.evals.evalops --export-dataset eval-dataset.jsonl
   ```

   Every row carries `inputs.case_ref`, a hash of the question text. That is the key that ties a result back to its case.
3. **Create a project API key** in EvalOps (shown once) and set the gate policy for the project.
4. **Add to the CiteSure repository** (Settings, Secrets and variables, Actions):
   - secret `EVALOPS_URL`, for example `https://evalops.example.com`
   - secret `EVALOPS_API_KEY`
   - variable `EVALOPS_DATASET_ID`, the id of the dataset from step 2
5. Push to `main`. The first run has no `main` baseline yet; `--bootstrap-ok` (used only on pushes) records it as the first one. From then on, PRs are compared with the latest `main` run.

Without the secrets (for example on a PR from a fork) the EvalOps step is skipped and the committed-baseline check is the only gate.

## When you add a golden question

`golden.jsonl` and the EvalOps dataset must list the same questions. EvalOps refuses results that do not match the dataset exactly, because a partial run would inflate the pass rate. So after adding a question with the `add-golden-question` skill:

1. Re-export the dataset with the command above.
2. Add the new case to the EvalOps dataset (import the new row, or add it in the UI).

Until you do, CI fails with an explicit message, `results must cover the dataset exactly; unknown case_ref: ...`. That failure is intended: it is the reminder to sync.

## Failure modes

| Exit code of `publish_to_evalops.py` | Meaning |
|---|---|
| 0 | EvalOps answered `pass` |
| 1 | EvalOps answered `fail`; the reasons and a compare link are in the job summary |
| 2 | no verdict: EvalOps unreachable or erroring (it retries 5xx twice), a wrong key or dataset id, or a dataset mismatch |

An exit code of 2 fails the job on purpose. A gate that quietly skips itself when its backend is down is not a gate.

## Trying it locally

```bash
# terminal 1: EvalOps (see its README), then create a project, import the dataset, create a key
# terminal 2: the CiteSure database must be up (docker compose up db), then
cd backend
uv run python -m app.evals.run --matrix evals/experiments.yaml --cases-out eval-cases.json
EVALOPS_API_KEY=eo_... python evals/publish_to_evalops.py eval-cases.json \
    --url http://localhost:8000 --dataset-id 1 --head-label main --baseline-label main --bootstrap-ok
```

## Real or private data: what EvalOps stores

The shipped golden set and the CI run use the fictional corpus, so EvalOps only ever sees invented questions. If you run the same pipeline over a **real** corpus, set `PRIVATE_MODE=true` (or pass `--redact` to `python -m app.evals.run` and `python -m app.evals.evalops`):

| | Normal | `PRIVATE_MODE` / `--redact` |
|---|---|---|
| Dataset row `inputs.question` | the question | `[redacted]` |
| Dataset row `expected_output` | the reference answer | `[redacted]` (`[refused]` is kept) |
| Result `output` | the answer text | `[answered]` or `[refused]` |
| Everything the gate needs | `case_ref`, pass/fail, score, latency, tags | the same |

The gate works identically, because it compares per-question pass/fail and scores, never words. Verified against a live EvalOps: 40 redacted cases imported; the first `main` run passed at 85 percent; an identical pull request passed with 0 regressions; flipping one question made it fail (82 percent, 1 regression, exit code 1); EvalOps' stored results contain only the placeholders. EvalOps' own real-model evaluators (`LLM_PROVIDER=anthropic` there) would send case text to their provider, so do not import real company questions into a project that uses them.

## Where EvalOps runs

CI only needs `EVALOPS_URL` to be reachable from the runner. Free ways to get that, with the CiteSure stack staying private: [free-deployment.md](free-deployment.md).
