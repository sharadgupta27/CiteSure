"""Fail the build when a RAG change makes the metrics worse than the committed baseline.

    python evals/check_regression.py eval-results.json evals/baseline.json --config hybrid+rerank

Both files map configuration name -> metrics (the output of `python -m app.evals.run --out`).
Higher is better for every metric except `answerable_refusal_rate`. The hard gate on restricted questions
(`restricted_refusal_accuracy` must be 1.0) is enforced by the evaluation run itself; it is repeated here too.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOLERANCE = 0.02  # a metric may move by two points before the build fails (noise on a 40-question set)
LOWER_IS_BETTER = {"answerable_refusal_rate"}
CHECKED = [
    "recall_at_k",
    "mrr",
    "correctness",
    "faithfulness",
    "citation_precision",
    "citation_recall",
    "refusal_accuracy",
    "answerable_refusal_rate",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("current", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--config", default="hybrid+rerank")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE)
    args = parser.parse_args()

    current = json.loads(args.current.read_text(encoding="utf-8"))[args.config]
    if current["restricted_refusal_accuracy"] < 1.0:
        print(f"FAIL restricted_refusal_accuracy = {current['restricted_refusal_accuracy']:.2f} (must be 1.00)")
        return 1
    if not args.baseline.exists():
        print(f"No baseline at {args.baseline}; nothing to compare. Commit one with the current results.")
        return 0
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))[args.config]

    failures = []
    for metric in CHECKED:
        delta = current[metric] - baseline[metric]
        worse = delta > args.tolerance if metric in LOWER_IS_BETTER else delta < -args.tolerance
        status = "FAIL" if worse else "ok"
        print(f"{status:4} {metric:28} baseline={baseline[metric]:.2f} current={current[metric]:.2f} change={delta:+.2f}")
        if worse:
            failures.append(metric)
    if failures:
        print(f"\nRegression in: {', '.join(failures)}.")
        print("If the change is intended, update evals/baseline.json and explain why in the PR.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
