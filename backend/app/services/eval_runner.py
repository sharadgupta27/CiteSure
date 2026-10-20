"""Runs the golden set through the real pipeline and computes the metrics.

Questions are asked as *personas* (a plain member, or a member of the group named in `ask_as`), so the ACL
is exercised exactly as it is for real users: a restricted question asked by a plain member must be refused.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SYSTEM_EMAIL_DOMAIN, Settings
from app.models import GoldenQuestion
from app.providers import Providers
from app.rag.generation.prompt import JUDGE_PROMPT, load_prompt
from app.rag.text import normalise_ws
from app.rag.types import PipelineConfig
from app.repositories import documents as documents_repo
from app.repositories import evals as evals_repo
from app.repositories import users as users_repo
from app.repositories import workspaces as workspaces_repo
from app.security import hash_password
from app.services import acl
from app.services.ask import outcome_to_json
from app.services.pipeline import PipelineOutcome, run_pipeline

PERSONA_DOMAIN = SYSTEM_EMAIL_DOMAIN


async def ensure_persona(session: AsyncSession, workspace_id: uuid.UUID, ask_as: str | None) -> uuid.UUID:
    """A synthetic member used only by the evaluator. It has an unusable password, so nobody can log in as it."""
    slug = re.sub(r"[^a-z0-9]+", "-", (ask_as or "member").lower()).strip("-") or "member"
    email = f"eval-{slug}-{str(workspace_id)[:8]}@{PERSONA_DOMAIN}"
    user = await users_repo.get_by_email(session, email)
    if user is None:
        user = await users_repo.create_user(session, email, await hash_password(uuid.uuid4().hex))
        await workspaces_repo.add_membership(session, user.id, workspace_id, "member")
    if ask_as:
        group = await workspaces_repo.group_by_name(session, workspace_id, ask_as)
        if group is not None:
            await workspaces_repo.add_group_member(session, group.id, user.id)
    await session.flush()
    return user.id


@dataclass
class ItemResult:
    golden: GoldenQuestion
    outcome: PipelineOutcome
    hit_rank: int | None
    scores: dict[str, float]
    cited_relevant: int = 0
    cited_total: int = 0


@dataclass
class RunTotals:
    items: list[ItemResult] = field(default_factory=list)


def _relevant_sets(golden: GoldenQuestion, index: list[tuple[uuid.UUID, str, str]]) -> list[set[uuid.UUID]]:
    """For each expected quote, the chunk ids that contain it. Quotes survive any re-chunking; chunk ids do not."""
    sets: list[set[uuid.UUID]] = []
    for expected in golden.expected_quotes:
        needle = normalise_ws(expected["quote"]).lower()
        sets.append(
            {cid for cid, name, text in index if name == expected["document"] and needle in normalise_ws(text).lower()}
        )
    return sets


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


async def score_item(
    providers: Providers, golden: GoldenQuestion, outcome: PipelineOutcome, relevant: list[set[uuid.UUID]]
) -> ItemResult:
    retrieved_ids = [c.chunk_id for c in outcome.retrieved]
    hit_rank = next((i for i, cid in enumerate(retrieved_ids, 1) if any(cid in r for r in relevant)), None)
    cited = {c.chunk.chunk_id for claim in outcome.claims for c in claim.citations}
    relevant_union = set().union(*relevant) if relevant else set()
    scores: dict[str, float] = {}
    if golden.answerable:
        found = sum(1 for r in relevant if r & set(retrieved_ids))
        scores["recall"] = found / len(relevant) if relevant else 0.0
        scores["reciprocal_rank"] = 1.0 / hit_rank if hit_rank else 0.0
        scores["citation_recall"] = sum(1 for r in relevant if r & cited) / len(relevant) if relevant else 0.0
        if outcome.status == "answered" and golden.expected_answer:
            # Reuse the answer text exactly as a user would read it
            text = " ".join(claim.text for claim in outcome.claims)
            verdict, _ = await providers.llm.judge_correctness(
                system=load_prompt(JUDGE_PROMPT), question=golden.question, expected=golden.expected_answer, actual=text
            )
            scores["correctness"] = verdict.score
        else:
            scores["correctness"] = 0.0
    scores["refused"] = 1.0 if outcome.status == "refused" else 0.0
    return ItemResult(
        golden=golden,
        outcome=outcome,
        hit_rank=hit_rank,
        scores=scores,
        cited_relevant=len(cited & relevant_union),
        cited_total=len(cited),
    )


def aggregate(results: list[ItemResult]) -> dict[str, float | int]:
    answerable = [r for r in results if r.golden.answerable]
    unanswerable = [r for r in results if not r.golden.answerable]
    restricted = [r for r in unanswerable if "restricted" in (r.golden.tags or [])]
    drafted = sum(r.outcome.drafted for r in results)
    verified = sum(len(r.outcome.claims) for r in results)
    cited_total = sum(r.cited_total for r in results)
    return {
        "n_questions": len(results),
        "recall_at_k": _mean([r.scores["recall"] for r in answerable]),
        "mrr": _mean([r.scores["reciprocal_rank"] for r in answerable]),
        "correctness": _mean([r.scores["correctness"] for r in answerable]),
        "faithfulness": round(verified / drafted, 4) if drafted else 1.0,
        "citation_precision": round(sum(r.cited_relevant for r in results) / cited_total, 4) if cited_total else 1.0,
        "citation_recall": _mean([r.scores["citation_recall"] for r in answerable]),
        "refusal_accuracy": _mean([r.scores["refused"] for r in unanswerable]),
        "restricted_refusal_accuracy": _mean([r.scores["refused"] for r in restricted]),
        "answerable_refusal_rate": _mean([r.scores["refused"] for r in answerable]),
    }


async def run_golden_set(
    session: AsyncSession,
    providers: Providers,
    settings: Settings,
    workspace_id: uuid.UUID,
    golden_questions: list[GoldenQuestion],
    config: PipelineConfig,
) -> list[ItemResult]:
    filenames = sorted({q["document"] for g in golden_questions for q in g.expected_quotes})
    index = await documents_repo.chunks_by_document_name_for_worker(session, workspace_id, filenames)
    personas: dict[str | None, uuid.UUID] = {}
    results: list[ItemResult] = []
    for golden in golden_questions:
        if golden.ask_as not in personas:
            personas[golden.ask_as] = await ensure_persona(session, workspace_id, golden.ask_as)
            await session.commit()
        allowed = await acl.allowed_collection_ids(session, personas[golden.ask_as], workspace_id)
        outcome: PipelineOutcome | None = None
        async for kind, payload in run_pipeline(
            session, providers, settings, allowed_collection_ids=allowed, question=golden.question, config=config
        ):
            if kind == "result":
                assert isinstance(payload, PipelineOutcome)
                outcome = payload
        assert outcome is not None
        results.append(await score_item(providers, golden, outcome, _relevant_sets(golden, index)))
    return results


async def execute_eval_run(session: AsyncSession, providers: Providers, settings: Settings, run_id: uuid.UUID) -> None:
    run = await evals_repo.get_run(session, run_id)
    if run is None:
        return
    await evals_repo.set_run_state(session, run_id, "running")
    await evals_repo.delete_items(session, run_id)
    await session.commit()
    try:
        golden = list(await evals_repo.list_golden(session, run.workspace_id))
        if not golden:
            raise ValueError("The golden set is empty")
        config = PipelineConfig(**run.config)
        results = await run_golden_set(session, providers, settings, run.workspace_id, golden, config)
        for r in results:
            await evals_repo.add_item(
                session,
                eval_run_id=run_id,
                golden_question_id=r.golden.id,
                question=r.golden.question,
                answerable=r.golden.answerable,
                answer_status=r.outcome.status,
                hit_rank=r.hit_rank,
                retrieved_chunk_ids=[c.chunk_id for c in r.outcome.retrieved],
                answer_json=outcome_to_json(r.outcome),
                scores=r.scores,
            )
        await evals_repo.set_run_state(session, run_id, "done", metrics=aggregate(results))
        await session.commit()
    except Exception as exc:
        await session.rollback()
        await evals_repo.set_run_state(session, run_id, "failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
        await session.commit()


def format_table(rows: list[tuple[str, dict[str, Any]]]) -> str:
    """Markdown table: one row per named configuration."""
    columns = [
        ("recall_at_k", "recall@k"),
        ("mrr", "MRR"),
        ("correctness", "correct"),
        ("faithfulness", "faithful"),
        ("citation_precision", "cite-P"),
        ("citation_recall", "cite-R"),
        ("refusal_accuracy", "refuse-acc"),
        ("restricted_refusal_accuracy", "restricted"),
        ("answerable_refusal_rate", "wrong-refusal"),
    ]
    header = "| config | " + " | ".join(label for _, label in columns) + " |"
    divider = "|" + "---|" * (len(columns) + 1)
    lines = [header, divider]
    for name, metrics in rows:
        lines.append(f"| {name} | " + " | ".join(f"{metrics[key]:.2f}" for key, _ in columns) + " |")
    return "\n".join(lines)
