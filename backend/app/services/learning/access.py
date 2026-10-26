"""Shared access checks for the learning layer. All of them reuse services/acl.py, the only place that decides who may
read what; nothing here makes its own authorization decision."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import Conflict, NotFound
from app.models import Document
from app.repositories import learning_sources as sources_repo
from app.services import acl


async def readable_documents(
    session: AsyncSession, context: acl.AccessContext, document_ids: Sequence[uuid.UUID], *, require_ready: bool = False
) -> list[Document]:
    """The documents, in the order given (duplicates removed). If any id is unknown, in another workspace or in a
    collection the caller may not read, the answer is the same 404: which one it was is never revealed."""
    unique = list(dict.fromkeys(document_ids))
    rows = await sources_repo.readable_documents(session, unique, allowed_collection_ids=context.allowed_collection_ids)
    if len(rows) != len(unique):
        raise NotFound("Document not found")
    by_id = {row.id: row for row in rows}
    ordered = [by_id[i] for i in unique]
    if require_ready and any(row.status != "ready" for row in ordered):
        raise Conflict("A document is still being processed; try again when it is ready")
    return ordered


async def readable_document(
    session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID, workspace_id: uuid.UUID | None = None
) -> Document:
    """One document the user may read in any of their workspaces (or in `workspace_id`)."""
    allowed = await acl.allowed_collection_ids(session, user_id, workspace_id)
    rows = await sources_repo.readable_documents(session, [document_id], allowed_collection_ids=allowed)
    if not rows:
        raise NotFound("Document not found")
    return rows[0]
