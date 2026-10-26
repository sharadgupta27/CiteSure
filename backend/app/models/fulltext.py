"""Phase 3 tables: the public full-text cache and the requests that fill it. Migration 0003 creates them.

The cache is deliberately NOT the `chunks` table. `chunks` is the internal corpus and every query on it is filtered by
the asker's collections; a published paper belongs to no collection and to no ACL. Separate tables mean internal
retrieval cannot return a public passage and public retrieval cannot return company text, whatever a query forgets.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.config import EMBEDDING_DIM
from app.models.base import Base, TZDateTime, new_id, utcnow


class FullTextPaper(Base):
    """One cached open-access paper. `id` is the same uuid5 the abstract passages use as their document id, so a
    citation of the abstract and a citation of the full text name the same paper."""

    __tablename__ = "fulltext_papers"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    paper_key: Mapped[str] = mapped_column(String(300), unique=True)  # doi:..., arxiv:..., europepmc:..., openalex:...
    doi: Mapped[str | None] = mapped_column(String(300), nullable=True)
    url: Mapped[str] = mapped_column(Text)  # the paper's landing page: what a citation links to
    title: Mapped[str] = mapped_column(String(500))
    label: Mapped[str] = mapped_column(String(600))  # "Title (Lovelace et al., 2024)", as shown in citations
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_host: Mapped[str] = mapped_column(String(255))  # where the PDF came from (a host, never a query)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, server_default=text("now()"))
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)


class FullTextChunk(Base):
    __tablename__ = "fulltext_chunks"
    __table_args__ = (
        Index("ix_fulltext_chunks_paper_ord", "paper_id", "ord"),
        Index("ix_fulltext_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_fulltext_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_id)
    paper_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("fulltext_papers.id", ondelete="CASCADE"))
    ord: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[Any] = mapped_column(TSVECTOR)


class FullTextRequest(Base):
    """A user's ask to add a paper's full text. It carries the status the UI polls and the budget accounting."""

    __tablename__ = "fulltext_requests"
    __table_args__ = (
        Index("ix_fulltext_requests_workspace_created", "workspace_id", "created_at"),
        CheckConstraint("status IN ('queued','running','ready','failed')", name="status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    paper_key: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="queued")
    error: Mapped[str | None] = mapped_column(String(60), nullable=True)  # a reason code (no_open_access, ...), never text
    counted: Mapped[bool] = mapped_column(Boolean, default=False)  # charged against the workspace's daily budget
    cached: Mapped[bool] = mapped_column(Boolean, default=False)  # answered from the cache, nothing was downloaded
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("fulltext_papers.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(600), nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    egress: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # [{destination, status, reason}]
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, server_default=text("now()"))
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
