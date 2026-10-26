from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import current_user, evaluation_service
from app.api.deps_admin import audit_log
from app.schemas import api as s
from app.services import audit as audit_actions
from app.services.audit import AuditLog
from app.services.evaluation import EvaluationService

router = APIRouter(tags=["evaluation"])


@router.get(
    "/workspaces/{workspace_id}/golden-questions", operation_id="listGoldenQuestions", response_model=list[s.GoldenQuestion]
)
async def list_golden(
    workspace_id: uuid.UUID, user: s.User = Depends(current_user), svc: EvaluationService = Depends(evaluation_service)
) -> list[s.GoldenQuestion]:
    return await svc.list_golden(user.id, workspace_id)


@router.post(
    "/workspaces/{workspace_id}/golden-questions",
    operation_id="createGoldenQuestion",
    status_code=201,
    response_model=s.GoldenQuestion,
)
async def create_golden(
    workspace_id: uuid.UUID,
    body: s.GoldenQuestionCreate,
    user: s.User = Depends(current_user),
    svc: EvaluationService = Depends(evaluation_service),
    audit: AuditLog = Depends(audit_log),
) -> s.GoldenQuestion:
    golden = await svc.create_golden(user.id, workspace_id, body)
    await audit.record(
        user, audit_actions.GOLDEN_CREATE, f"golden:{golden.id}", workspace_id, {"answerable": golden.answerable}
    )
    return golden


@router.post(
    "/workspaces/{workspace_id}/golden-questions/from-feedback/{feedback_id}",
    operation_id="promoteFeedback",
    status_code=201,
    response_model=s.GoldenQuestion,
)
async def promote_feedback(
    workspace_id: uuid.UUID,
    feedback_id: uuid.UUID,
    body: s.PromoteFeedbackRequest,
    user: s.User = Depends(current_user),
    svc: EvaluationService = Depends(evaluation_service),
    audit: AuditLog = Depends(audit_log),
) -> s.GoldenQuestion:
    golden = await svc.promote_feedback(user.id, workspace_id, feedback_id, body)
    await audit.record(
        user,
        audit_actions.GOLDEN_PROMOTE,
        f"golden:{golden.id}",
        workspace_id,
        {"feedback_id": str(feedback_id), "answerable": golden.answerable},
    )
    return golden


@router.patch("/golden-questions/{golden_id}", operation_id="updateGoldenQuestion", response_model=s.GoldenQuestion)
async def update_golden(
    golden_id: uuid.UUID,
    body: s.GoldenQuestionUpdate,
    user: s.User = Depends(current_user),
    svc: EvaluationService = Depends(evaluation_service),
    audit: AuditLog = Depends(audit_log),
) -> s.GoldenQuestion:
    golden = await svc.update_golden(user.id, golden_id, body)
    await audit.record(user, audit_actions.GOLDEN_UPDATE, f"golden:{golden_id}", golden.workspace_id)
    return golden


@router.delete("/golden-questions/{golden_id}", operation_id="deleteGoldenQuestion", status_code=204)
async def delete_golden(
    golden_id: uuid.UUID,
    user: s.User = Depends(current_user),
    svc: EvaluationService = Depends(evaluation_service),
    audit: AuditLog = Depends(audit_log),
) -> Response:
    workspace_id = await audit.workspace_of("golden", golden_id)  # the row is gone after the delete
    await svc.delete_golden(user.id, golden_id)
    await audit.record(user, audit_actions.GOLDEN_DELETE, f"golden:{golden_id}", workspace_id)
    return Response(status_code=204)


@router.get("/workspaces/{workspace_id}/eval-runs", operation_id="listEvalRuns", response_model=list[s.EvalRun])
async def list_runs(
    workspace_id: uuid.UUID, user: s.User = Depends(current_user), svc: EvaluationService = Depends(evaluation_service)
) -> list[s.EvalRun]:
    return await svc.list_runs(user.id, workspace_id)


@router.post("/workspaces/{workspace_id}/eval-runs", operation_id="createEvalRun", status_code=202, response_model=s.EvalRun)
async def create_run(
    workspace_id: uuid.UUID,
    body: s.EvalRunCreate,
    user: s.User = Depends(current_user),
    svc: EvaluationService = Depends(evaluation_service),
    audit: AuditLog = Depends(audit_log),
) -> s.EvalRun:
    run = await svc.create_run(user.id, workspace_id, body)
    await audit.record(
        user,
        audit_actions.EVAL_RUN,
        f"eval_run:{run.id}",
        workspace_id,
        {
            "retrieval_mode": body.config.retrieval_mode,
            "rerank": body.config.rerank,
            "candidate_k": body.config.candidate_k,
            "top_k": body.config.top_k,
        },
    )
    return run


# Declared before /eval-runs/{run_id} so "compare" is not parsed as a run id.
@router.get("/eval-runs/compare", operation_id="compareEvalRuns", response_model=s.EvalCompare)
async def compare_runs(
    base: uuid.UUID = Query(...),
    head: uuid.UUID = Query(...),
    user: s.User = Depends(current_user),
    svc: EvaluationService = Depends(evaluation_service),
) -> s.EvalCompare:
    return await svc.compare(user.id, base, head)


@router.get("/eval-runs/{run_id}", operation_id="getEvalRun", response_model=s.EvalRunDetail)
async def get_run(
    run_id: uuid.UUID, user: s.User = Depends(current_user), svc: EvaluationService = Depends(evaluation_service)
) -> s.EvalRunDetail:
    return await svc.get_run(user.id, run_id)


@router.get("/retrieval/explain", operation_id="explainRetrieval", response_model=s.RetrievalExplain)
async def explain_retrieval(
    workspace_id: uuid.UUID = Query(...),
    query: str = Query(..., min_length=1, max_length=2000),
    retrieval_mode: Literal["vector", "hybrid"] = Query("hybrid"),
    rerank: bool = Query(True),
    user: s.User = Depends(current_user),
    svc: EvaluationService = Depends(evaluation_service),
) -> s.RetrievalExplain:
    return await svc.explain(user.id, workspace_id, query, retrieval_mode, rerank)
