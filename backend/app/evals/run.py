"""Evaluation harness.

    python -m app.evals.run --config default
    python -m app.evals.run --matrix evals/experiments.yaml --md ../docs/eval-results.generated.md

It seeds the demo corpus into a throw-away workspace (one per chunk size), runs the golden set through the real
pipeline for every configuration, prints a metrics table, and cleans up. With LLM_PROVIDER=fake and
EMBEDDING_PROVIDER=fake it is deterministic, free and offline (this is what CI runs on every PR).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import delete

from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.models import User, Workspace
from app.providers import build_providers
from app.rag.types import PipelineConfig
from app.repositories import evals as evals_repo
from app.seed import seed_demo
from app.services.eval_runner import PERSONA_DOMAIN, ItemResult, aggregate, format_table, run_golden_set
from app.services.pipeline import default_config

GATES = {"restricted_refusal_accuracy": 1.0}  # hard requirement: a restricted question is NEVER answered


def describe_failures(name: str, items: list[ItemResult]) -> list[str]:
    lines = []
    for r in items:
        wrong_refusal = r.golden.answerable and r.outcome.status == "refused"
        wrong_answer = not r.golden.answerable and r.outcome.status == "answered"
        missed = r.golden.answerable and r.hit_rank is None
        if wrong_refusal or wrong_answer or missed or (r.golden.answerable and r.scores.get("correctness", 1) < 1):
            kind = "REFUSED" if wrong_refusal else "ANSWERED" if wrong_answer else "MISSED" if missed else "PARTIAL"
            claims = " | ".join(c.text for c in r.outcome.claims)[:90]
            lines.append(
                f"[{name}] {kind:8} {r.golden.question[:60]:60} rank={r.hit_rank} "
                f"drafted={r.outcome.drafted} dropped={r.outcome.dropped} {claims}"
            )
    return lines


def load_experiments(path: Path | None, settings: Settings) -> list[dict[str, Any]]:
    if path is None:
        base = default_config(settings)
        return [{"name": "default", "chunk_tokens": settings.chunk_tokens, **base.as_dict()}]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = default_config(settings).as_dict()
    return [{"chunk_tokens": settings.chunk_tokens, **defaults, **item} for item in data["experiments"]]


async def run(
    experiments: list[dict[str, Any]], settings: Settings, failures: list[str] | None = None
) -> list[tuple[str, dict[str, Any]]]:
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    results: list[tuple[str, dict[str, Any]]] = []
    created_workspaces: list[uuid.UUID] = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_settings = settings.model_copy(update={"storage_path": tmp, "storage_backend": "local"})
            providers = build_providers(run_settings)
            by_chunk: dict[int, list[dict[str, Any]]] = {}
            for experiment in experiments:
                by_chunk.setdefault(int(experiment["chunk_tokens"]), []).append(experiment)
            for chunk_tokens, group in by_chunk.items():
                # Each chunk size needs its own index, so each gets its own workspace.
                tuned = run_settings.model_copy(update={"chunk_tokens": chunk_tokens})
                seeded = await seed_demo(
                    sessionmaker, providers, tuned, workspace_name=f"eval-{chunk_tokens}-{uuid.uuid4().hex[:6]}"
                )
                created_workspaces.append(seeded.workspace_id)
                async with sessionmaker() as session:
                    golden = list(await evals_repo.list_golden(session, seeded.workspace_id))
                    for experiment in group:
                        config = PipelineConfig(
                            retrieval_mode=experiment["retrieval_mode"],
                            rerank=bool(experiment["rerank"]),
                            candidate_k=int(experiment["candidate_k"]),
                            top_k=int(experiment["top_k"]),
                        )
                        items = await run_golden_set(session, providers, tuned, seeded.workspace_id, golden, config)
                        results.append((experiment["name"], aggregate(items)))
                        if failures is not None:
                            failures += describe_failures(experiment["name"], items)
        return results
    finally:
        async with sessionmaker() as session:  # remove the throw-away data, including synthetic eval personas
            await session.execute(delete(User).where(User.email.like(f"eval-%@{PERSONA_DOMAIN}")))
            for workspace_id in created_workspaces:
                await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.commit()
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="default", help="only 'default' (the settings-based pipeline) is built in")
    parser.add_argument("--matrix", type=Path, help="experiments.yaml with several configurations")
    parser.add_argument("--out", type=Path, help="write all metrics as JSON")
    parser.add_argument("--show-failures", action="store_true", help="print questions that were refused, missed or wrong")
    parser.add_argument("--md", type=Path, help="write the markdown table to a file")
    args = parser.parse_args()

    settings = get_settings()
    experiments = load_experiments(args.matrix, settings)
    failures: list[str] | None = [] if args.show_failures else None
    results = asyncio.run(run(experiments, settings, failures))
    table = format_table(results)
    print(
        f"\nProviders: llm={settings.llm_provider} embeddings={settings.embedding_provider} reranker={settings.reranker}\n"
    )
    print(table)
    for line in failures or []:
        print(line)
    if args.out:
        args.out.write_text(json.dumps({name: metrics for name, metrics in results}, indent=2), encoding="utf-8")
    if args.md:
        args.md.write_text(table + "\n", encoding="utf-8")

    failed = [
        f"{name}: {metric} = {metrics[metric]:.2f} (required {minimum:.2f})"
        for name, metrics in results
        for metric, minimum in GATES.items()
        if metrics[metric] < minimum
    ]
    for line in failed:
        print("GATE FAILED", line, file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
