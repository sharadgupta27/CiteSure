"""Nightly regression agent.

A scheduled, non-interactive agent (no human in the loop, so it is deliberately boring and fully deterministic):

    1. read this night's evaluation results and the previous night's,
    2. decide whether any metric regressed beyond the tolerance (or a restricted question was answered),
    3. suggest likely causes from the pattern of metrics, and (optionally, with --api) from per-question evidence
       such as the rank of the first relevant chunk and what `/retrieval/explain` returns,
    4. open ONE GitHub issue (or comment on the open one) with the table and the suspects.

It never changes code, data or the golden set. Its only side effect is the issue.

    python custom-agent/agent.py --results eval-results.json --previous evals/last-nightly.json --config hybrid+rerank --open-issue
    python custom-agent/agent.py --results eval-results.json --dry-run     # print the report only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

TOLERANCE = 0.02
LOWER_IS_BETTER = {"answerable_refusal_rate"}
METRICS = [
    "recall_at_k",
    "mrr",
    "correctness",
    "faithfulness",
    "citation_precision",
    "citation_recall",
    "refusal_accuracy",
    "restricted_refusal_accuracy",
    "answerable_refusal_rate",
]
# What a pattern of regressions usually means in this codebase, and where to look first.
SUSPECTS: dict[str, tuple[str, str]] = {
    "restricted_refusal_accuracy": (
        "CRITICAL: a restricted question was answered. Access control or the refusal policy is broken.",
        "Stop the release. Run `uv run pytest tests/integration/test_acl_leaks.py`, review recent changes to `services/acl.py` and `rag/retrieval/`.",
    ),
    "recall_at_k": (
        "Relevant chunks are no longer being retrieved.",
        "Check chunking (`rag/chunking`), the embedder (`EMBEDDING_MODEL`), `candidate_k`/`top_k`. Use the `retrieval-debugger` subagent on a failing question.",
    ),
    "mrr": (
        "The right chunk is retrieved but ranked lower.",
        "Check fusion (`rag/retrieval/fusion.py`) and the reranker model. Compare `explain_retrieval` before/after.",
    ),
    "faithfulness": (
        "The model drafts more claims that verification rejects.",
        "Check the answer prompt version, `ANSWER_MODEL`, and whether quotes still match chunk text (parsing changed whitespace?).",
    ),
    "citation_precision": (
        "Citations point at chunks that do not contain the expected evidence.",
        "Check prompt changes and chunk boundaries (a fact split across two chunks).",
    ),
    "citation_recall": (
        "Answers cite fewer of the expected sources.",
        "Check `top_k` and the generation prompt.",
    ),
    "correctness": (
        "Answers are less often right.",
        "Check `ANSWER_MODEL`/`VERIFY_MODEL`, prompts, and whether answerable questions are now refused.",
    ),
    "refusal_accuracy": (
        "Out-of-scope questions are answered instead of refused.",
        "Check the prompt's refuse rule and entailment strictness (`VERIFY_MODEL`).",
    ),
    "answerable_refusal_rate": (
        "Answerable questions are refused more often (verification too strict or recall lower).",
        "Check `QUOTE_MATCH_MIN`, quote normalisation, and retrieval recall for the refused questions.",
    ),
}


@dataclass
class Change:
    metric: str
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before

    @property
    def regressed(self) -> bool:
        return self.delta > TOLERANCE if self.metric in LOWER_IS_BETTER else self.delta < -TOLERANCE


def compare(current: dict[str, float], previous: dict[str, float] | None) -> tuple[list[Change], list[Change]]:
    """Returns (all changes, regressions). The restricted-question gate is absolute: anything below 1.0 is a regression."""
    changes = [Change(m, (previous or current).get(m, current[m]), current[m]) for m in METRICS if m in current]
    regressions = [c for c in changes if c.regressed]
    gate = next((c for c in changes if c.metric == "restricted_refusal_accuracy"), None)
    if gate and gate.after < 1.0 and gate not in regressions:
        regressions.insert(0, gate)
    return changes, regressions


def classify_question(item: dict[str, Any]) -> str:
    """Which stage most likely lost this question, from the evidence the evaluation stores per question."""
    if item["answerable"] and item["answer_status"] == "refused":
        if item["hit_rank"] is None:
            return "retrieval or chunking: the expected chunk was not in the context given to the model"
        if item["hit_rank"] > 3:
            return f"ranking: the expected chunk was only rank {item['hit_rank']}"
        return "generation or verification: the right chunk was retrieved but no verified claim survived"
    if not item["answerable"] and item["answer_status"] == "answered":
        return "access control or refusal policy: a question that must be refused was answered"
    return "answer quality"


def render_report(config: str, changes: list[Change], regressions: list[Change], extra: list[str]) -> str:
    lines = [
        f"## Nightly RAG evaluation regressed (`{config}`)",
        "",
        "| metric | previous | tonight | change |",
        "|---|---|---|---|",
    ]
    for c in changes:
        flag = " ⚠️" if c in regressions else ""
        lines.append(f"| {c.metric} | {c.before:.2f} | {c.after:.2f} | {c.delta:+.2f}{flag} |")
    lines += ["", "### Suspected causes"]
    for c in regressions:
        what, where = SUSPECTS[c.metric]
        lines.append(f"- **{c.metric}** ({c.before:.2f} -> {c.after:.2f}): {what} {where}")
    if extra:
        lines += ["", "### Questions that got worse", *extra]
    lines += [
        "",
        "Run the matrix locally: `cd backend && uv run python -m app.evals.run --matrix evals/experiments.yaml --show-failures`, then use the "
        "`retrieval-debugger` subagent and the `tune-retrieval` skill. Do not edit the golden set to make this pass.",
        "",
        "_Opened by `custom-agent/agent.py`. It makes no other changes._",
    ]
    return "\n".join(lines)


async def question_evidence(api: str, email: str, password: str) -> list[str]:
    """Per-question evidence from a running CiteSure: classify the worst items of the latest run, and show the top-3
    retrieved documents for each (via /retrieval/explain) so the issue is actionable."""
    async with httpx.AsyncClient(base_url=api.rstrip("/") + "/api/v1", timeout=60) as client:
        login = await client.post("/auth/login", json={"email": email, "password": password})
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        workspaces = (await client.get("/workspaces", headers=headers)).json()
        workspace_id = workspaces[0]["id"]
        runs = [r for r in (await client.get(f"/workspaces/{workspace_id}/eval-runs", headers=headers)).json() if r["status"] == "done"]
        if not runs:
            return []
        detail = (await client.get(f"/eval-runs/{runs[0]['id']}", headers=headers)).json()
        bad = [
            i
            for i in detail["items"]
            if (i["answerable"] and i["answer_status"] == "refused") or (not i["answerable"] and i["answer_status"] == "answered")
        ][:5]
        lines = []
        for item in bad:
            trace = (
                await client.get("/retrieval/explain", params={"workspace_id": workspace_id, "query": item["question"]}, headers=headers)
            ).json()
            top = ", ".join(c["document_title"] for c in trace["reranked"][:3]) or "nothing"
            lines.append(f"- “{item['question']}”: {classify_question(item)}. Top retrieved: {top}.")
        return lines


def github_issue(report: str, config: str, repo: str, token: str, transport: httpx.BaseTransport | None = None) -> str:
    """Open one issue per regression, or comment on the existing open one (no duplicate every night)."""
    title = f"Nightly RAG regression: {config}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    with httpx.Client(base_url="https://api.github.com", headers=headers, timeout=30, transport=transport) as client:
        existing = client.get(f"/repos/{repo}/issues", params={"state": "open", "labels": "rag-regression", "per_page": 20})
        existing.raise_for_status()
        match = next((i for i in existing.json() if i["title"] == title), None)
        if match:
            comment = client.post(f"/repos/{repo}/issues/{match['number']}/comments", json={"body": report})
            comment.raise_for_status()
            return f"commented on #{match['number']}"
        created = client.post(f"/repos/{repo}/issues", json={"title": title, "body": report, "labels": ["rag-regression"]})
        created.raise_for_status()
        return f"opened #{created.json()['number']}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, required=True, help="JSON from `python -m app.evals.run --out`")
    parser.add_argument("--previous", type=Path, help="last night's JSON")
    parser.add_argument("--config", default="hybrid+rerank")
    parser.add_argument("--api", help="base URL of a running CiteSure, for per-question evidence")
    parser.add_argument("--open-issue", action="store_true", help="create/comment a GitHub issue (needs GITHUB_TOKEN, GITHUB_REPOSITORY)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--update-previous", action="store_true", help="overwrite --previous with tonight's results")
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args(argv)

    current = json.loads(args.results.read_text(encoding="utf-8"))[args.config]
    previous = None
    if args.previous and args.previous.exists():
        previous = json.loads(args.previous.read_text(encoding="utf-8")).get(args.config)
    changes, regressions = compare(current, previous)

    if args.update_previous and args.previous:
        args.previous.write_text(args.results.read_text(encoding="utf-8"), encoding="utf-8")
    if not regressions:
        print(f"No regression for {args.config}: all {len(changes)} metrics are within {TOLERANCE:.2f} of the previous run.")
        return 0

    extra: list[str] = []
    if args.api:
        import asyncio

        try:
            extra = asyncio.run(
                question_evidence(args.api, os.environ.get("CITESURE_MCP_EMAIL", "admin@acme.example"), os.environ["CITESURE_MCP_PASSWORD"])
            )
        except (httpx.HTTPError, KeyError) as exc:
            extra = [f"- (could not collect per-question evidence: {type(exc).__name__})"]
    report = render_report(args.config, changes, regressions, extra)
    print(report)
    if args.open_issue and not args.dry_run:
        token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        if not token or not repo:
            print("\nCannot open an issue: set GITHUB_TOKEN and GITHUB_REPOSITORY.", file=sys.stderr)
            return 2
        print("\n" + github_issue(report, args.config, repo, token))
    return 1 if args.fail_on_regression else 0


if __name__ == "__main__":
    sys.exit(main())
