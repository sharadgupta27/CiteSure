"""Maps the golden-set run to EvalOps' vocabulary (project 1), so EvalOps can gate CiteSure in CI.

EvalOps stores one *case* per question and one *result* per case and run. The pure functions here turn an
`ItemResult` into that result and a golden question into a dataset row; `scripts/publish_to_evalops.py` does the HTTP.

A question *passes* when the system did the right thing for it:
- an unanswerable or restricted question: it was refused (answering it is the failure the product exists to prevent);
- an answerable question: it was answered, the expected source was retrieved, and the judge scored the answer at
  least `MIN_CORRECTNESS`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.rag.text import normalise_ws
from app.services.eval_runner import ItemResult

MIN_CORRECTNESS = 0.5  # the judge scores 0, 0.5 or 1; half credit still counts as an answer a user could act on
MAX_OUTPUT_CHARS = 5000  # EvalOps rejects a longer `output`


def case_ref(question: str) -> str:
    """A stable key for a question. Golden rows keep no id of their own, and the text is what identifies a question."""
    digest = hashlib.sha256(normalise_ws(question).lower().encode("utf-8")).hexdigest()
    return f"q-{digest[:12]}"


def case_passed(item: ItemResult) -> bool:
    if not item.golden.answerable:
        return item.outcome.status == "refused"
    return (
        item.outcome.status == "answered"
        and item.hit_rank is not None
        and item.scores.get("correctness", 0.0) >= MIN_CORRECTNESS
    )


def case_score(item: ItemResult) -> float:
    if not item.golden.answerable:
        return 1.0 if item.outcome.status == "refused" else 0.0
    return round(item.scores.get("correctness", 0.0), 4) if item.outcome.status == "answered" else 0.0


REDACTED = "[redacted]"


def case_output(item: ItemResult, *, redact: bool = False) -> str:
    """The answer text EvalOps stores. With `redact`, only the outcome: the gate needs pass/fail, score and latency,
    not the words, so real company answers need never leave the system that produced them."""
    if item.outcome.status == "refused":
        return "[refused]"
    if redact:
        return "[answered]"
    return " ".join(claim.text for claim in item.outcome.claims)


def to_ingest_results(items: list[ItemResult], *, redact: bool = False) -> list[dict[str, Any]]:
    """The `results` array of EvalOps' POST /gate/ingest."""
    return [
        {
            "case_ref": case_ref(item.golden.question),
            "output": case_output(item, redact=redact)[:MAX_OUTPUT_CHARS],
            "passed": case_passed(item),
            "score": case_score(item),
            "latency_ms": round(sum(item.outcome.timings.values()), 1),
        }
        for item in items
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the golden set as an EvalOps dataset import file (JSONL).")
    parser.add_argument("--export-dataset", type=Path, required=True)
    parser.add_argument("--golden", type=Path, default=Path(__file__).resolve().parents[2] / "evals" / "golden.jsonl")
    parser.add_argument(
        "--redact",
        action="store_true",
        help="replace question and reference-answer text with placeholders (implied by PRIVATE_MODE=true)",
    )
    args = parser.parse_args()
    redact = args.redact or get_settings().private_mode
    rows = golden_to_dataset_rows(args.golden.read_text(encoding="utf-8").splitlines(), redact=redact)
    args.export_dataset.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} cases to {args.export_dataset}")
    return 0


def golden_to_dataset_rows(golden_lines: list[str], *, redact: bool = False) -> list[str]:
    """JSONL for EvalOps' dataset import: `case_ref` is what ties a result back to its case.

    With `redact`, the question and reference answer are placeholders. The `case_ref` is a truncated hash, so the
    questions themselves stay on this side; the tags remain so EvalOps can still show results by category."""
    rows = []
    for line in golden_lines:
        if not line.strip():
            continue
        item = json.loads(line)
        rows.append(
            json.dumps(
                {
                    "inputs": {
                        "case_ref": case_ref(item["question"]),
                        "question": REDACTED if redact else item["question"],
                    },
                    "expected_output": (REDACTED if redact and item["expected_answer"] else item["expected_answer"])
                    or "[refused]",
                    "tags": item.get("tags", []),
                },
                ensure_ascii=False,
            )
        )
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
