"""The admin dashboard: operational numbers for one workspace over the last N days."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.repositories import dashboard as repo
from app.schemas import admin as a
from app.services import acl


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def fill_days(rows: list[dict[str, Any]], first: date, last: date) -> list[a.DashboardDay]:
    """One entry per calendar day, zeros for the days with no questions, so a chart's x axis has no holes."""
    by_day = {r["day"]: r for r in rows}
    days: list[a.DashboardDay] = []
    day = first
    while day <= last:
        r = by_day.get(day)
        days.append(
            a.DashboardDay(
                date=day,
                questions=int(r["questions"]) if r else 0,
                answered=int(r["answered"]) if r else 0,
                refused=int(r["refused"]) if r else 0,
                cost_usd=round(float(r["cost_usd"]), 6) if r else 0.0,
            )
        )
        day += timedelta(days=1)
    return days


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID, workspace_id: uuid.UUID, days: int) -> a.Dashboard:
        context = await acl.require_admin(self.session, user_id, workspace_id)
        collections = context.allowed_collection_ids  # an admin reads every collection of the workspace
        now = utcnow()
        today = now.astimezone(UTC).date()
        first = today - timedelta(days=days - 1)
        since = datetime(first.year, first.month, first.day, tzinfo=UTC)

        day_rows = await repo.question_days(self.session, workspace_id, since)
        totals = await repo.question_totals(self.session, workspace_id, since)
        p50, p95 = await repo.latency_percentiles(self.session, workspace_id, since)
        statuses = await repo.document_status_counts(self.session, collections)
        up, down = await repo.feedback_counts(self.session, workspace_id, since)
        failures = await repo.recent_failed_documents(self.session, collections)

        questions = sum(int(r["questions"]) for r in day_rows)
        answered = sum(int(r["answered"]) for r in day_rows)
        refused = sum(int(r["refused"]) for r in day_rows)
        cost = sum(float(r["cost_usd"]) for r in day_rows)
        shown, dropped = int(totals["claims_shown"]), int(totals["claims_dropped"])
        failed_docs = dict(statuses).get("failed", 0)
        return a.Dashboard(
            workspace_id=workspace_id,
            days=days,
            generated_at=now,
            questions=a.DashboardQuestions(
                total=questions,
                answered=answered,
                refused=refused,
                refusal_rate=_rate(refused, questions),
                claims_shown=shown,
                claims_dropped=dropped,
                dropped_claim_rate=_rate(dropped, shown + dropped),
            ),
            per_day=fill_days(day_rows, first, today),
            latency=a.DashboardLatency(
                p50_ms=None if p50 is None else round(p50, 1), p95_ms=None if p95 is None else round(p95, 1)
            ),
            cost=a.DashboardCost(
                total_usd=round(cost, 6),
                per_question_usd=round(cost / questions, 6) if questions else 0.0,
                tokens_in=int(totals["tokens_in"]),
                tokens_out=int(totals["tokens_out"]),
            ),
            documents=a.DashboardDocuments(
                total=sum(n for _, n in statuses),
                chunks=await repo.chunk_count(self.session, collections),
                by_status=[a.DashboardCount(label=s, count=n) for s, n in statuses],
            ),
            ingest=a.DashboardIngest(
                failed_documents=failed_docs,
                failed_jobs=await repo.failed_ingest_jobs(self.session, collections, since),
                recent_failures=[
                    a.IngestFailure(document_id=f["id"], title=f["title"], error=f["error"], created_at=f["created_at"])
                    for f in failures
                ],
            ),
            egress=[
                a.DashboardEgress(destination=d, status=st, count=n)
                for d, st, n in await repo.egress_counts(self.session, workspace_id, since)
            ],
            feedback=a.DashboardFeedback(up=up, down=down, positive_ratio=_rate(up, up + down) if up + down else None),
        )
