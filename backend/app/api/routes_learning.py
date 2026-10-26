"""Phase 4 routes: reading progress, study sets, learning plans, summarize and compare agents (docs/learning-layer.md).

Routers only parse and call services. Everything is per user: there is no admin view of someone else's progress,
sets or plans. The model-backed operations share the /ask rate limit bucket per user."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ask_limiter, current_user, get_providers, get_session, get_settings
from app.api.deps_admin import audit_log
from app.api.ratelimit import RateLimiter
from app.config import Settings
from app.providers import Providers
from app.schemas import api as api_schemas
from app.schemas import learning as s
from app.services.audit import AuditLog
from app.services.learning import AgentService, PlanService, ProgressService, StudySetService

router = APIRouter(tags=["learning"])


def progress_service(session: AsyncSession = Depends(get_session)) -> ProgressService:
    return ProgressService(session)


def study_set_service(session: AsyncSession = Depends(get_session)) -> StudySetService:
    return StudySetService(session)


def plan_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    providers: Providers = Depends(get_providers),
) -> PlanService:
    return PlanService(session, settings, providers)


def agent_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    providers: Providers = Depends(get_providers),
) -> AgentService:
    return AgentService(session, settings, providers)


# --- reading progress ----------------------------------------------------------------------
@router.get("/documents/{document_id}/progress", operation_id="getReadingProgress", response_model=s.ReadingProgress)
async def get_reading_progress(
    document_id: uuid.UUID, user: api_schemas.User = Depends(current_user), svc: ProgressService = Depends(progress_service)
) -> s.ReadingProgress:
    return await svc.get(user.id, document_id)


@router.put("/documents/{document_id}/progress", operation_id="updateReadingProgress", response_model=s.ReadingProgress)
async def update_reading_progress(
    document_id: uuid.UUID,
    body: s.ReadingProgressUpdate,
    user: api_schemas.User = Depends(current_user),
    svc: ProgressService = Depends(progress_service),
) -> s.ReadingProgress:
    return await svc.update(user.id, document_id, body)


@router.delete("/documents/{document_id}/progress", operation_id="resetReadingProgress", status_code=204)
async def reset_reading_progress(
    document_id: uuid.UUID, user: api_schemas.User = Depends(current_user), svc: ProgressService = Depends(progress_service)
) -> Response:
    await svc.reset(user.id, document_id)
    return Response(status_code=204)


@router.get(
    "/workspaces/{workspace_id}/reading-progress",
    operation_id="listReadingProgress",
    response_model=list[s.ReadingProgressItem],
)
async def list_reading_progress(
    workspace_id: uuid.UUID, user: api_schemas.User = Depends(current_user), svc: ProgressService = Depends(progress_service)
) -> list[s.ReadingProgressItem]:
    return await svc.list_recent(user.id, workspace_id)


# --- study sets ----------------------------------------------------------------------------
@router.get("/workspaces/{workspace_id}/study-sets", operation_id="listStudySets", response_model=list[s.StudySet])
async def list_study_sets(
    workspace_id: uuid.UUID,
    user: api_schemas.User = Depends(current_user),
    svc: StudySetService = Depends(study_set_service),
) -> list[s.StudySet]:
    return await svc.list_sets(user.id, workspace_id)


@router.post(
    "/workspaces/{workspace_id}/study-sets", operation_id="createStudySet", status_code=201, response_model=s.StudySetDetail
)
async def create_study_set(
    workspace_id: uuid.UUID,
    body: s.StudySetCreate,
    user: api_schemas.User = Depends(current_user),
    svc: StudySetService = Depends(study_set_service),
) -> s.StudySetDetail:
    return await svc.create(user.id, workspace_id, body)


@router.get("/study-sets/{study_set_id}", operation_id="getStudySet", response_model=s.StudySetDetail)
async def get_study_set(
    study_set_id: uuid.UUID,
    user: api_schemas.User = Depends(current_user),
    svc: StudySetService = Depends(study_set_service),
) -> s.StudySetDetail:
    return await svc.get(user.id, study_set_id)


@router.patch("/study-sets/{study_set_id}", operation_id="updateStudySet", response_model=s.StudySetDetail)
async def update_study_set(
    study_set_id: uuid.UUID,
    body: s.StudySetUpdate,
    user: api_schemas.User = Depends(current_user),
    svc: StudySetService = Depends(study_set_service),
) -> s.StudySetDetail:
    return await svc.update(user.id, study_set_id, body)


@router.delete("/study-sets/{study_set_id}", operation_id="deleteStudySet", status_code=204)
async def delete_study_set(
    study_set_id: uuid.UUID,
    user: api_schemas.User = Depends(current_user),
    svc: StudySetService = Depends(study_set_service),
) -> Response:
    await svc.delete(user.id, study_set_id)
    return Response(status_code=204)


@router.post(
    "/study-sets/{study_set_id}/items", operation_id="addStudySetItem", status_code=201, response_model=s.StudySetItem
)
async def add_study_set_item(
    study_set_id: uuid.UUID,
    body: s.StudySetItemCreate,
    user: api_schemas.User = Depends(current_user),
    svc: StudySetService = Depends(study_set_service),
) -> s.StudySetItem:
    return await svc.add_item(user.id, study_set_id, body)


@router.patch("/study-sets/{study_set_id}/items/{item_id}", operation_id="updateStudySetItem", response_model=s.StudySetItem)
async def update_study_set_item(
    study_set_id: uuid.UUID,
    item_id: uuid.UUID,
    body: s.StudySetItemUpdate,
    user: api_schemas.User = Depends(current_user),
    svc: StudySetService = Depends(study_set_service),
) -> s.StudySetItem:
    return await svc.update_item(user.id, study_set_id, item_id, body)


@router.delete("/study-sets/{study_set_id}/items/{item_id}", operation_id="removeStudySetItem", status_code=204)
async def remove_study_set_item(
    study_set_id: uuid.UUID,
    item_id: uuid.UUID,
    user: api_schemas.User = Depends(current_user),
    svc: StudySetService = Depends(study_set_service),
) -> Response:
    await svc.remove_item(user.id, study_set_id, item_id)
    return Response(status_code=204)


# --- learning plans ------------------------------------------------------------------------
@router.get(
    "/workspaces/{workspace_id}/learning-plans", operation_id="listLearningPlans", response_model=list[s.LearningPlanSummary]
)
async def list_learning_plans(
    workspace_id: uuid.UUID, user: api_schemas.User = Depends(current_user), svc: PlanService = Depends(plan_service)
) -> list[s.LearningPlanSummary]:
    return await svc.list_plans(user.id, workspace_id)


@router.post(
    "/workspaces/{workspace_id}/learning-plans",
    operation_id="createLearningPlan",
    status_code=201,
    response_model=s.LearningPlan,
)
async def create_learning_plan(
    workspace_id: uuid.UUID,
    body: s.LearningPlanCreate,
    user: api_schemas.User = Depends(current_user),
    svc: PlanService = Depends(plan_service),
    limiter: RateLimiter = Depends(ask_limiter),
    audit: AuditLog = Depends(audit_log),
) -> s.LearningPlan:
    limiter.check(f"learn:{user.id}")
    plan = await svc.create(user.id, workspace_id, body)
    await audit.record(user, "learning.plan_create", str(plan.id), workspace_id, {"steps": plan.steps_total})
    return plan


@router.get("/learning-plans/{plan_id}", operation_id="getLearningPlan", response_model=s.LearningPlan)
async def get_learning_plan(
    plan_id: uuid.UUID, user: api_schemas.User = Depends(current_user), svc: PlanService = Depends(plan_service)
) -> s.LearningPlan:
    return await svc.get(user.id, plan_id)


@router.delete("/learning-plans/{plan_id}", operation_id="deleteLearningPlan", status_code=204)
async def delete_learning_plan(
    plan_id: uuid.UUID,
    user: api_schemas.User = Depends(current_user),
    svc: PlanService = Depends(plan_service),
    audit: AuditLog = Depends(audit_log),
) -> Response:
    await svc.delete(user.id, plan_id)
    await audit.record(user, "learning.plan_delete", str(plan_id))
    return Response(status_code=204)


@router.patch("/learning-plans/{plan_id}/steps/{step_id}", operation_id="updatePlanStep", response_model=s.LearningPlan)
async def update_plan_step(
    plan_id: uuid.UUID,
    step_id: uuid.UUID,
    body: s.PlanStepUpdate,
    user: api_schemas.User = Depends(current_user),
    svc: PlanService = Depends(plan_service),
) -> s.LearningPlan:
    return await svc.set_step_done(user.id, plan_id, step_id, body.done)


# --- summarize and compare ------------------------------------------------------------------
@router.post(
    "/workspaces/{workspace_id}/learning/summarize", operation_id="summarizeDocument", response_model=api_schemas.Answer
)
async def summarize_document(
    workspace_id: uuid.UUID,
    body: s.SummarizeRequest,
    user: api_schemas.User = Depends(current_user),
    svc: AgentService = Depends(agent_service),
    limiter: RateLimiter = Depends(ask_limiter),
    audit: AuditLog = Depends(audit_log),
) -> api_schemas.Answer:
    limiter.check(f"learn:{user.id}")
    answer = await svc.summarize(user.id, workspace_id, body)
    await audit.record(user, "learning.summarize", str(answer.id), workspace_id, {"status": answer.status})
    return answer


@router.post(
    "/workspaces/{workspace_id}/learning/compare", operation_id="compareDocuments", response_model=api_schemas.Answer
)
async def compare_documents(
    workspace_id: uuid.UUID,
    body: s.CompareRequest,
    user: api_schemas.User = Depends(current_user),
    svc: AgentService = Depends(agent_service),
    limiter: RateLimiter = Depends(ask_limiter),
    audit: AuditLog = Depends(audit_log),
) -> api_schemas.Answer:
    limiter.check(f"learn:{user.id}")
    answer = await svc.compare(user.id, workspace_id, body)
    await audit.record(user, "learning.compare", str(answer.id), workspace_id, {"status": answer.status})
    return answer
