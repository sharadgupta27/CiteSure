"""Ingestion: parse -> clean -> chunk -> PII scan -> embed -> index. Runs in the worker, never in a request."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import UnsupportedMedia
from app.observability import INGEST_DOCS
from app.providers import Providers
from app.rag import pii
from app.rag.chunking import chunk_sections
from app.rag.parsing import OcrOptions, ParseError, detect, parse_document
from app.repositories import documents as documents_repo

EMBED_BATCH = 64


def embedding_input(title: str, heading_path: list[str], text: str) -> str:
    """Chunks are embedded with their document title and headings, so 'Section 4.2' still knows what it is about."""
    context = " > ".join([title, *heading_path])
    return f"{context}\n{text}"


def fts_input(title: str, heading_path: list[str], text: str) -> str:
    return " ".join([title, *heading_path, text])


async def ingest_document(
    session: AsyncSession,
    providers: Providers,
    settings: Settings,
    document_id: uuid.UUID,
    *,
    chunk_tokens: int | None = None,
) -> None:
    doc = await documents_repo.get_for_worker(session, document_id)
    if doc is None:  # deleted while queued
        return
    try:
        await documents_repo.set_status(session, document_id, "parsing")
        await session.commit()

        data = await providers.blobs.get(doc.blob_key)
        detected = detect(data)
        ocr = OcrOptions(settings.ocr_enabled, settings.ocr_languages, settings.ocr_dpi, settings.ocr_max_pages)
        parsed = await asyncio.to_thread(parse_document, detected.kind, data, doc.filename, ocr=ocr)
        sections = parsed.sections
        if settings.pii_redact:  # before chunking, so character offsets match the stored text
            sections = [replace(sec, text=pii.redact(sec.text)) for sec in sections]
        _, drafts = chunk_sections(
            sections, target_tokens=chunk_tokens or settings.chunk_tokens, overlap=settings.chunk_overlap
        )
        if not drafts:
            raise ParseError("The document has no text")

        doc.title = parsed.title[:300]
        await documents_repo.set_status(session, document_id, "embedding", page_count=parsed.page_count)
        await session.commit()

        inputs = [embedding_input(parsed.title, d.heading_path, d.text) for d in drafts]
        vectors: list[list[float]] = []
        for start in range(0, len(inputs), EMBED_BATCH):
            vectors += await providers.embedder.embed_documents(inputs[start : start + EMBED_BATCH])

        rows = [
            {
                "ord": d.ord,
                "text": d.text,
                "heading_path": d.heading_path,
                "page_start": d.page_start,
                "page_end": d.page_end,
                "char_start": d.char_start,
                "char_end": d.char_end,
                "token_count": d.token_count,
                "embedding": vector,
                "fts_text": fts_input(parsed.title, d.heading_path, d.text),
                "pii_flags": pii.scan(d.text),
            }
            for d, vector in zip(drafts, vectors, strict=True)
        ]
        await documents_repo.replace_chunks(session, document_id, doc.collection_id, rows)
        await documents_repo.set_status(session, document_id, "ready", error=None)
        await session.commit()
        INGEST_DOCS.labels(status="ready").inc()
    except (ParseError, UnsupportedMedia) as exc:  # the file itself is the problem: retrying cannot help
        await session.rollback()
        await documents_repo.set_status(session, document_id, "failed", error=str(exc)[:500])
        await session.commit()
        INGEST_DOCS.labels(status="failed").inc()
    except Exception as exc:
        await session.rollback()
        # Only the exception TYPE is stored. Messages from drivers and parsers can echo the data they were processing
        # (document text), and this column is shown to admins and kept in the database.
        await documents_repo.set_status(
            session,
            document_id,
            "failed",
            error=f"Ingestion failed ({type(exc).__name__}). It will be retried; see the worker logs.",
        )
        await session.commit()
        INGEST_DOCS.labels(status="error").inc()
        raise  # let the job queue retry with backoff
