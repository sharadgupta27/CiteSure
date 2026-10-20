#!/usr/bin/env python3
"""Send CiteSure's per-question evaluation results to EvalOps and fail the build on its verdict.

    python -m app.evals.run --matrix evals/experiments.yaml --cases-out eval-cases.json
    EVALOPS_API_KEY=eo_... python evals/publish_to_evalops.py eval-cases.json \
        --url https://evalops.example.com --dataset-id 3 --head-label pr-42 --baseline-label main --git-sha "$GITHUB_SHA"

Standard library only. Exit codes follow EvalOps' own gate client: 0 = pass, 1 = fail, 2 = usage or infrastructure error.
One-time setup: `python -m app.evals.evalops --export-dataset eval-dataset.jsonl`, then import that file into a new
EvalOps dataset (Datasets -> Import). `case_ref` in each row is what ties a result back to its case.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ATTEMPTS = 3


class EvalOpsError(SystemExit):
    """EvalOps answered with an error status. A SystemExit so an unexpected one ends the script with its message."""

    def __init__(self, status: int, detail: str, url: str) -> None:
        super().__init__(f"EvalOps answered {status} to POST {url}: {detail}")
        self.status = status
        self.detail = detail


def post(url: str, key: str, body: dict[str, Any]) -> dict[str, Any]:
    if not url.startswith(("http://", "https://")):  # urllib would also open file:// URLs
        raise SystemExit(f"--url must be an http(s) URL, got {url!r}")
    data = json.dumps(body).encode("utf-8")
    for attempt in range(1, ATTEMPTS + 1):
        req = urllib.request.Request(url, data=data, method="POST")  # noqa: S310  # nosemgrep
        req.add_header("X-API-Key", key)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  # nosemgrep
                result: dict[str, Any] = json.loads(resp.read())
                return result
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:1500]
            if e.code >= 500 and attempt < ATTEMPTS:  # a restarting EvalOps is not a quality failure
                time.sleep(2 * attempt)
                continue
            raise EvalOpsError(e.code, detail, url) from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < ATTEMPTS:
                time.sleep(2 * attempt)
                continue
            raise SystemExit(f"cannot reach EvalOps at {url}: {e}") from e
    raise AssertionError("unreachable")


def summary_markdown(result: dict[str, Any], base_url: str) -> str:
    icon = "✅" if result["verdict"] == "pass" else "❌"
    lines = [f"### {icon} EvalOps gate: **{result['verdict'].upper()}**", "", f"- Head run: `{result['run_id']}`"]
    if result["baseline_run_id"] is not None:
        lines.append(f"- Baseline run: `{result['baseline_run_id']}`")
        lines.append(f"- Compare: {base_url}/compare?base={result['baseline_run_id']}&head={result['run_id']}")
    lines += ["", *[f"- {reason}" for reason in result["reasons"]]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", type=Path, help="JSON written by `python -m app.evals.run --cases-out`")
    parser.add_argument("--url", default=os.environ.get("EVALOPS_URL"), help="EvalOps base URL (or EVALOPS_URL)")
    parser.add_argument("--dataset-id", type=int, required=True)
    parser.add_argument("--head-label", required=True, help="e.g. pr-42 or main")
    parser.add_argument("--baseline-label", help="gate against the latest run with this label, e.g. main")
    parser.add_argument(
        "--bootstrap-ok",
        action="store_true",
        help="when EvalOps has no version with --baseline-label yet (the very first run on main), record without one",
    )
    parser.add_argument("--git-sha")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to a code page that cannot print the status icon
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    key = os.environ.get("EVALOPS_API_KEY")
    if not key or not args.url:
        print("EVALOPS_API_KEY and --url (or EVALOPS_URL) are required", file=sys.stderr)
        return 2
    results = json.loads(args.cases.read_text(encoding="utf-8"))
    base = args.url.rstrip("/")
    body = {
        "dataset_id": args.dataset_id,
        "head_label": args.head_label,
        "baseline_label": args.baseline_label,
        "git_sha": args.git_sha,
        "results": results,
    }
    url = f"{base}/api/v1/gate/ingest"
    try:
        try:
            result = post(url, key, {k: v for k, v in body.items() if v is not None})
        except EvalOpsError as e:
            if not (args.bootstrap_ok and args.baseline_label and e.status == 404 and "baseline version" in e.detail):
                raise
            print(f"no '{args.baseline_label}' baseline in EvalOps yet; recording this run as the first one")
            body["baseline_label"] = None
            result = post(url, key, {k: v for k, v in body.items() if v is not None})
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2

    report = summary_markdown(result, base)
    print(report)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(report)
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
