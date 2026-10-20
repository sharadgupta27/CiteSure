"""Documents and chunks.

Every method that *reads* content takes `allowed_collection_ids` as a required keyword argument
and applies it in SQL (non-negotiable 1). Methods named `*_for_worker` are used only by the
ingestion worker, which acts for the system and never for a user request.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document

AllowedIds = Sequence[uuid.UUID]


async def create_document(
    session: AsyncSession,
    *,
    collection_id: uuid.UUID,
    title: str,
    filename: str,
    mime: str,
    sha256: str,
    blob_key: str,
    uploaded_by: uuid.UUID,
) -> Document:
    doc = Document(
        collection_id=collection_id,
        title=title,
        filename=filename,
        mime=mime,
        sha256=sha256,
        blob_key=blob_key,
        uploaded_by=uploaded_by,
    )
    session.add(doc)
    await session.flush()
    return doc


async def sha_exists(session: AsyncSession, collection_id: uuid.UUID, sha256: str) -> bool:
    stmt = select(Document.id).where(Document.collection_id == collection_id, Document.sha256 == sha256)
    return (await session.execute(stmt)).first() is not None


async def get_document(
    session: AsyncSession, document_id: uuid.UUID, *, allowed_collection_ids: AllowedIds
) -> tuple[Document, int] | None:
    stmt = (
        select(Document, func.count(Chunk.id))
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .where(Document.id == document_id, Document.collection_id.in_(allowed_collection_ids))
        .group_by(Document.id)
    )
    row = (await session.execute(stmt)).first()
    return (row[0], row[1]) if row else None


async def list_documents(
    session: AsyncSession, collection_id: uuid.UUID, *, allowed_collection_ids: AllowedIds
) -> list[tuple[Document, int]]:
    stmt = (
        select(Document, func.count(Chunk.id))
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .where(Document.collection_id == collection_id, Document.collection_id.in_(allowed_collection_ids))
        .group_by(Document.id)
        .order_by(Document.created_at)
    )
    return [(d, n) for d, n in (await session.execute(stmt)).all()]


async def list_chunks(
    session: AsyncSession, document_id: uuid.UUID, *, allowed_collection_ids: AllowedIds
) -> list[tuple[Chunk, str]]:
    stmt = (
        select(Chunk, Document.title)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.document_id == document_id, Chunk.collection_id.in_(allowed_collection_ids))
        .order_by(Chunk.ord)
    )
    return [(c, t) for c, t in (await session.execute(stmt)).all()]


async def get_chunk(
    session: AsyncSession, chunk_id: uuid.UUID, *, allowed_collection_ids: AllowedIds
) -> tuple[Chunk, str] | None:
    stmt = (
        select(Chunk, Document.title)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id == chunk_id, Chunk.collection_id.in_(allowed_collection_ids))
    )
    row = (await session.execute(stmt)).first()
    return (row[0], row[1]) if row else None


async def visible_chunk_ids(
    session: AsyncSession, chunk_ids: Sequence[uuid.UUID], *, allowed_collection_ids: AllowedIds
) -> set[uuid.UUID]:
    """Which of these chunk ids may the caller still read? Used to re-check stored answers."""
    if not chunk_ids:
        return set()
    stmt = select(Chunk.id).where(Chunk.id.in_(chunk_ids), Chunk.collection_id.in_(allowed_collection_ids))
    return set((await session.execute(stmt)).scalars().all())


async def get_for_worker(session: AsyncSession, document_id: uuid.UUID) -> Document | None:
    return await session.get(Document, document_id)


async def get_for_admin(
    session: AsyncSession, document_id: uuid.UUID, *, allowed_collection_ids: AllowedIds
) -> Document | None:
    stmt = select(Document).where(Document.id == document_id, Document.collection_id.in_(allowed_collection_ids))
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_status(
    session: AsyncSession,
    document_id: uuid.UUID,
    status: str,
    *,
    error: str | None = None,
    page_count: int | None = None,
) -> None:
    values: dict[str, Any] = {"status": status, "error": error}
    if page_count is not None:
        values["page_count"] = page_count
    await session.execute(update(Document).where(Document.id == document_id).values(**values))


async def replace_chunks(
    session: AsyncSession, document_id: uuid.UUID, collection_id: uuid.UUID, rows: Sequence[dict[str, Any]]
) -> None:
    """Swap all chunks of a document in one transaction, so a reindex never leaves a half-indexed document.

    Each row needs: ord, text, heading_path, page_start, page_end, char_start, char_end, token_count,
    embedding, fts_text (heading context + text, used only to build the tsvector), pii_flags.
    """
    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    for row in rows:
        values = {k: v for k, v in row.items() if k != "fts_text"}
        session.add(
            Chunk(
                document_id=document_id,
                collection_id=collection_id,
                # computed by Postgres so the text-search configuration lives in one place (the database)
                tsv=func.to_tsvector(literal_column("'english'::regconfig"), row["fts_text"]),
                **values,
            )
        )
    await session.flush()


async def delete_document(session: AsyncSession, document_id: uuid.UUID) -> None:
    await session.execute(delete(Document).where(Document.id == document_id))


async def count_by_status(session: AsyncSession) -> dict[str, int]:
    rows = (await session.execute(select(Document.status, func.count()).group_by(Document.status))).all()
    return {status: n for status, n in rows}


async def chunks_by_document_name_for_worker(
    session: AsyncSession, workspace_id: uuid.UUID, filenames: Sequence[str]
) -> list[tuple[uuid.UUID, str, str]]:
    """(chunk_id, filename, text) for the named documents in a workspace. System use only (evaluation harness):
    it resolves golden-set quotes to chunks, it never serves content to a user."""
    from app.models import Collection

    stmt = (
        select(Chunk.id, Document.filename, Chunk.text)
        .join(Document, Document.id == Chunk.document_id)
        .join(Collection, Collection.id == Document.collection_id)
        .where(Collection.workspace_id == workspace_id, Document.filename.in_(list(filenames)))
        .order_by(Document.filename, Chunk.ord)
    )
    return [(i, f, t) for i, f, t in (await session.execute(stmt)).all()]


async def chunk_ids_for_document_for_worker(session: AsyncSession, document_id: uuid.UUID) -> list[uuid.UUID]:
    """Chunk ids of one document, for erasure only (the ids themselves are not content)."""
    return list((await session.execute(select(Chunk.id).where(Chunk.document_id == document_id))).scalars().all())


async def chunk_ids_for_collection_for_worker(session: AsyncSession, collection_id: uuid.UUID) -> list[uuid.UUID]:
    return list((await session.execute(select(Chunk.id).where(Chunk.collection_id == collection_id))).scalars().all())
