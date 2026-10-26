"""Phase 2: a user's own highlights and notes on documents. Private to the author; see services/annotations.py."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_session
from app.api.deps_admin import audit_log
from app.schemas import api as s
from app.schemas import viewer as v
from app.services.annotations import AnnotationService
from app.services.audit import AuditLog

router = APIRouter(tags=["annotations"])


def annotation_service(session: AsyncSession = Depends(get_session)) -> AnnotationService:
    return AnnotationService(session)


@router.get("/documents/{document_id}/annotations", operation_id="listAnnotations", response_model=list[v.Annotation])
async def list_annotations(
    document_id: uuid.UUID, user: s.User = Depends(current_user), svc: AnnotationService = Depends(annotation_service)
) -> list[v.Annotation]:
    return await svc.list_for_document(user.id, document_id)


@router.post(
    "/documents/{document_id}/annotations", operation_id="createAnnotation", status_code=201, response_model=v.Annotation
)
async def create_annotation(
    document_id: uuid.UUID,
    body: v.AnnotationCreate,
    user: s.User = Depends(current_user),
    svc: AnnotationService = Depends(annotation_service),
    audit: AuditLog = Depends(audit_log),
) -> v.Annotation:
    created = await svc.create(user.id, document_id, body)
    await audit.record(user, "annotation.create", str(created.id), await audit.workspace_of("document", document_id))
    return created


@router.patch("/annotations/{annotation_id}", operation_id="updateAnnotation", response_model=v.Annotation)
async def update_annotation(
    annotation_id: uuid.UUID,
    body: v.AnnotationUpdate,
    user: s.User = Depends(current_user),
    svc: AnnotationService = Depends(annotation_service),
) -> v.Annotation:
    return await svc.update(user.id, annotation_id, body)


@router.delete("/annotations/{annotation_id}", operation_id="deleteAnnotation", status_code=204)
async def delete_annotation(
    annotation_id: uuid.UUID,
    user: s.User = Depends(current_user),
    svc: AnnotationService = Depends(annotation_service),
    audit: AuditLog = Depends(audit_log),
) -> Response:
    await svc.delete(user.id, annotation_id)
    await audit.record(user, "annotation.delete", str(annotation_id))
    return Response(status_code=204)
