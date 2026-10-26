"""Learning plans: an ordered list of reading steps over documents the user may read.

What is computed and what is generated:
- Computed from the documents' structure (never by a model): which steps exist, their order, title, pages, effort and
  week. Document order follows the study set, or for a topic: introductions first, then by relevance.
- Generated, then verified: each step's learning objective. It goes through the same generate -> verify -> refusal
  stages as /ask and is stored as an ordinary `answers` row, so every sentence carries a checked citation. Unsupported
  claims are dropped; a step with nothing supported shows a refusal (study-set plans) or is left out (topic plans)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import InvalidInput, NotFound
from app.models import Answer as AnswerRow
from app.models import Document
from app.models.base import utcnow
from app.models.learning import LearningPlan as PlanRow
from app.providers import Providers
from app.repositories import asks as asks_repo
from app.repositories import learning_plans as plans_repo
from app.repositories import learning_progress as progress_repo
from app.repositories import learning_sources as sources_repo
from app.schemas import api as api_schemas
from app.schemas import learning as s
from app.services import acl
from app.services.ask import AskService
from app.services.learning import access, grounded, layout, scoped
from app.services.learning.study_sets import StudySetService

PLAN_STEP_CHUNKS = 6  # passages the model reads per step
RANKED_PER_DOCUMENT = 3 * PLAN_STEP_CHUNKS  # topic mode: how many of a document's best passages are spread over its steps


@dataclass
class _Draft:
    """A step before it is stored."""

    unit: layout.Unit
    document: Document
    run: grounded.GroundedRun


class PlanService:
    def __init__(self, session: AsyncSession, settings: Settings, providers: Providers) -> None:
        self.session = session
        self.settings = settings
        self.providers = providers

    # --- create ---------------------------------------------------------------------------
    async def create(self, user_id: uuid.UUID, workspace_id: uuid.UUID, body: s.LearningPlanCreate) -> s.LearningPlan:
        context = await acl.context_for_workspace(self.session, user_id, workspace_id)
        study_set_id: uuid.UUID | None = None
        default_title = "Reading plan"
        if body.study_set_id is not None:
            row, _, readable_ids = await StudySetService(self.session).readable_document_ids(user_id, body.study_set_id)
            if row.workspace_id != workspace_id:
                raise NotFound("Study set not found")
            if not readable_ids:
                raise InvalidInput("This study set has no documents you can read")
            study_set_id, document_ids, default_title = row.id, readable_ids, row.name
        else:
            document_ids = list(dict.fromkeys(body.document_ids))
        topic = (body.topic or "").strip() or None
        limit = min(self.settings.learning_max_plan_documents, self.settings.learning_max_plan_steps)
        if len(document_ids) > limit:
            raise InvalidInput(f"A plan can cover at most {limit} documents")
        documents = await access.readable_documents(self.session, context, document_ids, require_ready=True)

        allowed = context.allowed_collection_ids
        metas = await sources_repo.chunk_meta(self.session, [d.id for d in documents], allowed_collection_ids=allowed)
        documents = [d for d in documents if metas.get(d.id)]
        if not documents:
            raise InvalidInput("The selected documents have no readable content yet")

        ranked: dict[uuid.UUID, list[uuid.UUID]] | None = None
        if topic is not None:
            ranked, documents = await self._rank_for_topic(topic, documents, allowed)

        units = self._units(documents, metas)
        drafts = await self._generate(units, documents, topic, ranked, allowed)
        if topic is not None:  # a step with no supported statement about the topic is noise in a topic plan
            drafts = [d for d in drafts if d.run.outcome.status == "answered"]
            if not drafts:
                raise InvalidInput("None of the selected documents contains a supported statement about this topic")
        title = (body.title or "").strip() or topic or default_title

        weeks = layout.assign_weeks([d.unit.minutes for d in drafts], body.hours_per_week)
        thread = await asks_repo.create_thread(self.session, user_id, workspace_id, f"Plan: {title}")
        plan = await plans_repo.create_plan(
            self.session,
            user_id=user_id,
            workspace_id=workspace_id,
            study_set_id=study_set_id,
            thread_id=thread.id,
            title=title[:200],
            topic=topic,
            hours_per_week=body.hours_per_week,
        )
        for position, (draft, week) in enumerate(zip(drafts, weeks, strict=True), start=1):
            question = f"Reading step {position}: {draft.document.title}" + (
                f" ({draft.unit.label})" if draft.unit.label else ""
            )
            answer = await grounded.store_run(
                self.session,
                self.settings,
                draft.run,
                user_id=user_id,
                workspace_id=workspace_id,
                thread_id=thread.id,
                question=question,
                task="plan_step",
            )
            await plans_repo.add_step(
                self.session,
                plan_id=plan.id,
                position=position,
                week=week,
                document_id=draft.document.id,
                label=draft.unit.label,
                page_start=draft.unit.page_start,
                page_end=draft.unit.page_end,
                ord_start=draft.unit.ord_start,
                ord_end=draft.unit.ord_end,
                est_minutes=draft.unit.minutes,
                answer_id=answer.id,
            )
        await self.session.commit()
        return (await self._views(user_id, [plan], context, with_steps=True))[0]

    async def _rank_for_topic(
        self, topic: str, documents: list[Document], allowed: tuple[uuid.UUID, ...]
    ) -> tuple[dict[uuid.UUID, list[uuid.UUID]], list[Document]]:
        """Each document's best passages for the topic, and the documents ordered: introductions, then most relevant."""
        vector = await self.providers.embedder.embed_query(topic)
        ranked: dict[uuid.UUID, list[uuid.UUID]] = {}
        relevance: list[tuple[uuid.UUID, str, float]] = []
        for document in documents:
            found = await scoped.top_chunks_in_document(
                self.session,
                self.providers,
                self.settings,
                query=topic,
                query_vector=vector,
                document_id=document.id,
                allowed_collection_ids=allowed,
                limit=RANKED_PER_DOCUMENT,
            )
            ranked[document.id] = [c.chunk_id for c in found]
            relevance.append((document.id, document.title, found[0].score if found else 0.0))
        by_id = {d.id: d for d in documents}
        return ranked, [by_id[i] for i in layout.order_by_topic(relevance)]

    def _units(self, documents: list[Document], metas: dict[uuid.UUID, list[sources_repo.ChunkMeta]]) -> list[layout.Unit]:
        budget = max(1, self.settings.learning_max_plan_steps // len(documents))
        units: list[layout.Unit] = []
        for document in documents:
            units.extend(
                layout.split_units(
                    metas[document.id],
                    words_per_minute=self.settings.learning_reading_wpm,
                    unit_minutes=self.settings.learning_unit_minutes,
                    max_units=budget,
                )
            )
        return units

    async def _generate(
        self,
        units: list[layout.Unit],
        documents: list[Document],
        topic: str | None,
        ranked: dict[uuid.UUID, list[uuid.UUID]] | None,
        allowed: tuple[uuid.UUID, ...],
    ) -> list[_Draft]:
        by_id = {d.id: d for d in documents}
        picks = [
            layout.pick_unit_chunks(u.chunk_ids, None if ranked is None else ranked.get(u.document_id, []), PLAN_STEP_CHUNKS)
            for u in units
        ]
        wanted = [cid for pick in picks for cid in pick]
        text = {
            c.chunk_id: c for c in await sources_repo.chunks_by_ids(self.session, wanted, allowed_collection_ids=allowed)
        }
        gate = asyncio.Semaphore(self.settings.learning_generation_concurrency)

        async def one(unit: layout.Unit, pick: list[uuid.UUID]) -> grounded.GroundedRun:
            document = by_id[unit.document_id]
            where = f'"{document.title}"' + (f" ({unit.label})" if unit.label else "")
            if topic is None:
                job = grounded.GroundedJob(
                    "summary", grounded.PLAN_STEP_PROMPT, f"State what a reader learns from this part of {where}."
                )
            else:
                job = grounded.GroundedJob(
                    "answer",
                    grounded.PLAN_STEP_PROMPT,
                    f"State what this part of {where} says about the topic: {topic}",
                    focus=topic,
                )
            chunks = sorted((text[c] for c in pick if c in text), key=lambda c: c.ord)
            async with gate:  # the model calls do not touch the session, so they can run side by side
                return await grounded.generate(self.providers, self.settings, chunks, job)

        results = await asyncio.gather(*(one(u, p) for u, p in zip(units, picks, strict=True)), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return [
            _Draft(unit, by_id[unit.document_id], run)
            for unit, run in zip(units, results, strict=True)
            if isinstance(run, grounded.GroundedRun)
        ]

    # --- read -----------------------------------------------------------------------------
    async def get(self, user_id: uuid.UUID, plan_id: uuid.UUID) -> s.LearningPlan:
        plan, context = await self._owned(user_id, plan_id)
        return (await self._views(user_id, [plan], context, with_steps=True))[0]

    async def list_plans(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> list[s.LearningPlanSummary]:
        context = await acl.context_for_workspace(self.session, user_id, workspace_id)
        plans = list(await plans_repo.list_plans(self.session, user_id, workspace_id))
        views = await self._views(user_id, plans, context, with_steps=False)
        return [s.LearningPlanSummary.model_validate(v.model_dump(exclude={"steps"})) for v in views]

    async def _owned(self, user_id: uuid.UUID, plan_id: uuid.UUID) -> tuple[PlanRow, acl.AccessContext]:
        plan = await plans_repo.get_plan(self.session, plan_id, user_id)
        if plan is None:
            raise NotFound("Learning plan not found")
        return plan, await acl.context_for_workspace(self.session, user_id, plan.workspace_id)

    async def _views(
        self, user_id: uuid.UUID, plans: list[PlanRow], context: acl.AccessContext, *, with_steps: bool
    ) -> list[s.LearningPlan]:
        visible = await plans_repo.visible_steps(
            self.session, [p.id for p in plans], allowed_collection_ids=context.allowed_collection_ids
        )
        progress = await progress_repo.for_documents(self.session, user_id, list({d.id for _, d, _ in visible}))
        objectives: dict[uuid.UUID, api_schemas.Answer] = {}
        if with_steps:
            rows: list[AnswerRow] = [a for _, _, a in visible if a is not None]
            # Re-check every citation against the caller's current access, exactly as GET /answers/{id} does.
            checked = await AskService(self.session, self.settings, self.providers)._recheck(user_id, rows)
            objectives = {answer.id: answer for answer in checked}
        views: list[s.LearningPlan] = []
        for plan in plans:
            mine = [(step, doc, answer) for step, doc, answer in visible if step.plan_id == plan.id]
            steps = [
                s.PlanStep(
                    id=step.id,
                    position=step.position,
                    week=step.week,
                    document_id=doc.id,
                    document_title=doc.title,
                    label=step.label,
                    page_start=step.page_start,
                    page_end=step.page_end,
                    est_minutes=step.est_minutes,
                    done=step.done_at is not None,
                    done_at=step.done_at,
                    reading_percent=progress[doc.id].percent if doc.id in progress else 0.0,
                    objective=objectives.get(answer.id) if answer is not None else None,
                )
                for step, doc, answer in mine
            ]
            done = sum(1 for step in steps if step.done)
            views.append(
                s.LearningPlan(
                    id=plan.id,
                    workspace_id=plan.workspace_id,
                    study_set_id=plan.study_set_id,
                    title=plan.title,
                    topic=plan.topic,
                    hours_per_week=plan.hours_per_week,
                    weeks=max((step.week for step in steps), default=0),
                    total_minutes=sum(step.est_minutes for step in steps),
                    steps_done=done,
                    steps_total=len(steps),
                    percent=round(100.0 * done / len(steps), 1) if steps else 0.0,
                    created_at=plan.created_at,
                    steps=steps if with_steps else [],
                )
            )
        return views

    # --- change ---------------------------------------------------------------------------
    async def set_step_done(self, user_id: uuid.UUID, plan_id: uuid.UUID, step_id: uuid.UUID, done: bool) -> s.LearningPlan:
        plan, context = await self._owned(user_id, plan_id)
        step = await plans_repo.get_step(self.session, plan.id, step_id)
        readable = (
            await sources_repo.readable_documents(
                self.session, [step.document_id], allowed_collection_ids=context.allowed_collection_ids
            )
            if step is not None
            else []
        )
        if step is None or not readable:  # a step whose document became unreadable is as good as gone
            raise NotFound("Plan step not found")
        when: datetime | None = utcnow() if done else None
        await plans_repo.set_done(self.session, step, when)
        await self.session.commit()
        return (await self._views(user_id, [plan], context, with_steps=True))[0]

    async def delete(self, user_id: uuid.UUID, plan_id: uuid.UUID) -> None:
        plan, _ = await self._owned(user_id, plan_id)
        thread_id = plan.thread_id
        await plans_repo.delete_plan(self.session, plan.id)
        if thread_id is not None:  # the objectives' answers live in the plan's own thread
            await plans_repo.delete_thread(self.session, thread_id)
        await self.session.commit()
