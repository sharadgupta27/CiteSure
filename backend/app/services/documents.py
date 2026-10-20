"""Uploading, listing, deleting and reading documents and chunks."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import PurePath

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import Conflict, Forbidden, NotFound, PayloadTooLarge, UnsupportedMedia
from app.models import Chunk as ChunkRow
from app.models import Document as DocumentRow
from app.rag.parsing import detect as detect_kind
from app.repositories import asks as asks_repo
from app.repositories import collections as collections_repo
from app.repositories import documents as documents_repo
from app.repositories import jobs as jobs_repo
from app.schemas import api as s
from app.services import acl
from app.storage.base import BlobStore

INGEST_JOB = "ingest_document"
_UNSAFE_NAME = re.compile(r"[^\w.\- ()]+")


def safe_filename(name: str) -> str:
    base = PurePath(name.replace("\\", "/")).name
    cleaned = _UNSAFE_NAME.sub("_", base).strip(" .")[:200]
    return cleaned or "document"


def to_document(row: DocumentRow, chunk_count: int) -> s.Document:
    return s.Document(
        id=row.id,
        collection_id=row.collection_id,
        title=row.title,
        filename=row.filename,
        mime=row.mime,
        sha256=row.sha256,
        status=row.status,
        page_count=row.page_count,
        chunk_count=chunk_count,
        error=row.error,
        created_at=row.created_at,
    )


def to_chunk(row: ChunkRow, document_title: str) -> s.Chunk:
    return s.Chunk(
        id=row.id,
        document_id=row.document_id,
        document_title=document_title,
        collection_id=row.collection_id,
        ord=row.ord,
        text=row.text,
        heading_path=list(row.heading_path or []),
        page_start=row.page_start,
        page_end=row.page_end,
        char_start=row.char_start,
        char_end=row.char_end,
    )


class DocumentService:
    def __init__(self, session: AsyncSession, settings: Settings, blobs: BlobStore) -> None:
        self.session = session
        self.settings = settings
        self.blobs = blobs

    async def _visible(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        return await acl.allowed_collection_ids(self.session, user_id)

    async def _admin_for_collection(self, user_id: uuid.UUID, collection_id: uuid.UUID):  # type: ignore[no-untyped-def]
        collection = await collections_repo.get(self.session, collection_id)
        if collection is None:
            raise NotFound("Collection not found")
        context = await acl.context_for_workspace(self.session, user_id, collection.workspace_id)
        if collection_id not in context.allowed_collection_ids:
            raise NotFound("Collection not found")
        if not context.is_admin:
            raise Forbidden("Only workspace admins can do this")
        return collection

    # --- write paths (admin only) ------------------------------------------------------------
    async def upload(
        self, user_id: uuid.UUID, collection_id: uuid.UUID, filename: str, data: bytes, *, enqueue: bool = True
    ) -> s.Document:
        if not self.settings.uploads_enabled:
            raise Forbidden("Uploads are disabled on this server")
        collection = await self._admin_for_collection(user_id, collection_id)
        if len(data) > self.settings.max_upload_bytes:
            raise PayloadTooLarge(f"Files can be at most {self.settings.max_upload_mb} MB")
        detected = detect_kind(data)  # raises UnsupportedMedia; the filename and Content-Type are never trusted
        sha = hashlib.sha256(data).hexdigest()
        if await documents_repo.sha_exists(self.session, collection_id, sha):
            raise Conflict("This file was already uploaded to this collection")
        name = safe_filename(filename)
        blob_key = f"{collection.workspace_id}/{collection_id}/{uuid.uuid4()}"
        await self.blobs.put(blob_key, data)
        try:
            row = await documents_repo.create_document(
                self.session,
                collection_id=collection_id,
                title=PurePath(name).stem.replace("-", " ").replace("_", " "),
                filename=name,
                mime=detected.mime,
                sha256=sha,
                blob_key=blob_key,
                uploaded_by=user_id,
            )
            if enqueue:  # the seed script and eval harness ingest inline and must not feed a queue someone else consumes
                await jobs_repo.enqueue(self.session, INGEST_JOB, {"document_id": str(row.id)})
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            await self.blobs.delete(blob_key)
            raise Conflict("This file was already uploaded to this collection") from exc
        return to_document(row, 0)

    async def delete(self, user_id: uuid.UUID, document_id: uuid.UUID) -> None:
        row = await self._admin_document(user_id, document_id)
        blob_key = row.blob_key
        # Erase quoted text from stored answers first: deleting a document must not leave its words behind.
        await asks_repo.scrub_deleted_chunks(
            self.session, await documents_repo.chunk_ids_for_document_for_worker(self.session, document_id)
        )
        await documents_repo.delete_document(self.session, document_id)  # chunks and embeddings cascade
        await self.session.commit()
        await self.blobs.delete(blob_key)

    async def reindex(self, user_id: uuid.UUID, document_id: uuid.UUID) -> s.Document:
        row = await self._admin_document(user_id, document_id)
        await documents_repo.set_status(self.session, document_id, "queued", error=None)
        await jobs_repo.enqueue(self.session, INGEST_JOB, {"document_id": str(document_id)})
        await self.session.commit()
        found = await documents_repo.get_document(self.session, document_id, allowed_collection_ids=[row.collection_id])
        assert found is not None
        return to_document(*found)

    async def _admin_document(self, user_id: uuid.UUID, document_id: uuid.UUID) -> DocumentRow:
        row = await documents_repo.get_for_admin(
            self.session, document_id, allowed_collection_ids=await self._visible(user_id)
        )
        if row is None:
            raise NotFound("Document not found")
        await self._admin_for_collection(user_id, row.collection_id)
        return row

    # --- read paths (every query is filtered by the caller's allowed collections) -------------
    async def list_in_collection(self, user_id: uuid.UUID, collection_id: uuid.UUID) -> list[s.Document]:
        rows = await documents_repo.list_documents(
            self.session, collection_id, allowed_collection_ids=await self._visible(user_id)
        )
        if not rows and collection_id not in await self._visible(user_id):
            raise NotFound("Collection not found")
        return [to_document(d, n) for d, n in rows]

    async def get_document(self, user_id: uuid.UUID, document_id: uuid.UUID) -> s.Document:
        found = await documents_repo.get_document(
            self.session, document_id, allowed_collection_ids=await self._visible(user_id)
        )
        if found is None:
            raise NotFound("Document not found")
        return to_document(*found)

    async def file(self, user_id: uuid.UUID, document_id: uuid.UUID) -> tuple[bytes, str, str]:
        row = await documents_repo.get_for_admin(
            self.session, document_id, allowed_collection_ids=await self._visible(user_id)
        )
        if row is None:
            raise NotFound("Document not found")
        return await self.blobs.get(row.blob_key), row.mime, row.filename

    async def chunks(self, user_id: uuid.UUID, document_id: uuid.UUID) -> list[s.Chunk]:
        visible = await self._visible(user_id)
        if await documents_repo.get_document(self.session, document_id, allowed_collection_ids=visible) is None:
            raise NotFound("Document not found")
        rows = await documents_repo.list_chunks(self.session, document_id, allowed_collection_ids=visible)
        return [to_chunk(c, title) for c, title in rows]

    async def chunk(self, user_id: uuid.UUID, chunk_id: uuid.UUID) -> s.Chunk:
        found = await documents_repo.get_chunk(self.session, chunk_id, allowed_collection_ids=await self._visible(user_id))
        if found is None:
            raise NotFound("Chunk not found")
        return to_chunk(*found)


__all__ = ["INGEST_JOB", "DocumentService", "UnsupportedMedia", "safe_filename"]
