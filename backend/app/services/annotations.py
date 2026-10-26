"""Highlights and notes on documents. Private to their author.

Two checks on every call: the annotation belongs to the caller (a row owned by someone else is a 404, as if it did not
exist), and the caller can still read the document (so losing access to a collection also hides your own highlights on
its documents, together with the quoted text). A document the caller cannot read is a 404, never a 403."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import InvalidInput, NotFound
from app.models import Document
from app.models.annotations import Annotation as AnnotationRow
from app.repositories import annotations as annotations_repo
from app.repositories import documents as documents_repo
from app.schemas import viewer as v
from app.services import acl

PDF_MIME = "application/pdf"


def to_annotation(row: AnnotationRow) -> v.Annotation:
    return v.Annotation(
        id=row.id,
        document_id=row.document_id,
        page=row.page,
        rects=[v.NormalizedRect(**r) for r in row.rects],
        text=row.text,
        note=row.note,
        color=row.color,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class AnnotationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _readable_document(self, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        allowed = await acl.allowed_collection_ids(self.session, user_id)
        found = await documents_repo.get_document(self.session, document_id, allowed_collection_ids=allowed)
        if found is None:
            raise NotFound("Document not found")
        return found[0]

    async def list_for_document(self, user_id: uuid.UUID, document_id: uuid.UUID) -> list[v.Annotation]:
        await self._readable_document(user_id, document_id)
        rows = await annotations_repo.list_for_document(self.session, document_id, user_id)
        return [to_annotation(r) for r in rows]

    async def create(self, user_id: uuid.UUID, document_id: uuid.UUID, body: v.AnnotationCreate) -> v.Annotation:
        document = await self._readable_document(user_id, document_id)
        if document.mime != PDF_MIME:
            raise InvalidInput("Highlights are available on PDF documents")
        if document.page_count is not None and body.page > document.page_count:
            raise InvalidInput(f"This document has {document.page_count} pages")
        row = await annotations_repo.create(
            self.session,
            document_id=document_id,
            user_id=user_id,
            page=body.page,
            rects=[r.model_dump() for r in body.rects],
            text=body.text,
            note=body.note,
            color=body.color,
        )
        await self.session.commit()
        return to_annotation(row)

    async def _owned(self, user_id: uuid.UUID, annotation_id: uuid.UUID) -> AnnotationRow:
        row = await annotations_repo.get_owned(self.session, annotation_id, user_id)
        if row is None:
            raise NotFound("Annotation not found")
        await self._readable_document(user_id, row.document_id)
        return row

    async def update(self, user_id: uuid.UUID, annotation_id: uuid.UUID, body: v.AnnotationUpdate) -> v.Annotation:
        row = await self._owned(user_id, annotation_id)
        await annotations_repo.update(self.session, row, note=body.note, color=body.color)
        await self.session.commit()
        return to_annotation(row)

    async def delete(self, user_id: uuid.UUID, annotation_id: uuid.UUID) -> None:
        row = await self._owned(user_id, annotation_id)
        await annotations_repo.delete_row(self.session, row.id, user_id)
        await self.session.commit()
