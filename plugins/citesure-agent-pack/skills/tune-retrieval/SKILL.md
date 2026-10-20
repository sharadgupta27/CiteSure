---
name: tune-retrieval
description: Improve retrieval or answer quality with evidence. Runs the experiment matrix, changes exactly one thing, re-runs, and reports a before/after table. Use when recall, MRR, faithfulness or refusal rates are low, when a golden question fails, or before changing chunking, retrieval, reranking, prompts or verification.
---

# Tune retrieval (measure, change one thing, measure again)

"Looks better" is not evidence (CLAUDE.md rule 3). This skill makes every RAG change a small experiment.

## Steps

1. **Baseline.** `cd backend && uv run python -m app.evals.run --matrix evals/experiments.yaml --show-failures --out /tmp/before.json`.
   Keep the table. Fake providers are the default (free, deterministic). The real-model run costs money: ask first.
2. **Diagnose before you tune.** Look at `--show-failures`. For each failure decide the stage at fault (use the MCP `explain_retrieval` tool
   or the `retrieval-debugger` subagent):
   | Symptom | Likely stage | Typical lever |
   |---|---|---|
   | right chunk absent from vector and keyword lists | parsing / chunking | chunk size, overlap, heading context |
   | in `fused` but missing from `reranked` | reranker | reranker model, `candidate_k`, `top_k` |
   | retrieved, but answer REFUSED | generation or verification | prompt, `QUOTE_MATCH_MIN`, entailment strictness |
   | ANSWERED a question that must be refused | generation | prompt; never relax ACL or verification |
3. **Change exactly one thing**, as configuration if possible (`backend/evals/experiments.yaml`, an env var), otherwise one small code or prompt change.
   Prompts are versioned files in `backend/app/rag/generation/prompts/`: add `answer_v2.md`, do not edit `answer_v1.md` in place.
4. **Re-run** the same command. Write the before/after rows in `docs/eval-results.md` with a one-line interpretation.
5. **Decide with the rules**:
   - `restricted_refusal_accuracy` must stay **1.00**. Any drop is a blocker, whatever else improved.
   - No other metric may fall by more than 0.02 without a written justification.
   - If the improvement is within noise (the golden set has 40 questions), say so and do not claim a win.
6. **Regression check**: `python backend/evals/check_regression.py /tmp/after.json backend/evals/baseline.json --config hybrid+rerank`.
   If the new numbers are better and intended, update `baseline.json` in the same change and explain why.
7. **Log it** in `docs/ai-workflow.md` (goal, change, numbers, what a human should review).

## Guardrails

- Never edit `backend/evals/golden*.jsonl` here. A failing golden question is the target, not the problem. Use `add-golden-question` to add coverage.
- Never weaken verification (`QUOTE_MATCH_MIN` below 0.9, accepting `partial` verdicts) or the ACL pre-filter to raise a metric.
- Chunk size or embedding changes need a reindex; changing the embedding model/dimension needs a migration and approval (CLAUDE.md rule 6).
