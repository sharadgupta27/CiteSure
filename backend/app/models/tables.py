"""All tables. Enumerations are VARCHAR + CHECK constraints (simple to migrate, readable in SQL)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import EMBEDDING_DIM
from app.models.base import Base, TZDateTime, new_id, utcnow


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_id)


def _fk(target: str, *, ondelete: str = "CASCADE", nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable)


def _created() -> Mapped[datetime]:
    return mapped_column(TZDateTime, default=utcnow, server_default=text("now()"))


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = _created()


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (CheckConstraint("role IN ('admin','member')", name="role"),)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(10))


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    name: Mapped[str] = mapped_column(String(100))


class GroupMember(Base):
    __tablename__ = "group_members"
    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name"),
        CheckConstraint("visibility IN ('workspace','groups')", name="visibility"),
    )
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    name: Mapped[str] = mapped_column(String(100))
    visibility: Mapped[str] = mapped_column(String(10), default="workspace")
    created_at: Mapped[datetime] = _created()


class CollectionGroup(Base):
    __tablename__ = "collection_groups"
    collection_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("collection_id", "sha256"),
        CheckConstraint("status IN ('queued','parsing','embedding','ready','failed')", name="status"),
    )
    id: Mapped[uuid.UUID] = _pk()
    collection_id: Mapped[uuid.UUID] = _fk("collections.id")
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    blob_key: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), default="queued")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = _fk("users.id", ondelete="SET NULL", nullable=True)
    created_at: Mapped[datetime] = _created()

    chunks: Mapped[list[Chunk]] = relationship(back_populates="document", passive_deletes=True)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_collection_id", "collection_id"),
        Index("ix_chunks_document_ord", "document_id", "ord"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = _fk("documents.id")
    # Denormalised from the document so the ACL filter runs in the same SQL as the vector search.
    collection_id: Mapped[uuid.UUID] = _fk("collections.id")
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
    pii_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_run_after", "status", "run_after"),
        CheckConstraint("status IN ('queued','running','done','failed')", name="status"),
    )
    id: Mapped[uuid.UUID] = _pk()
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, server_default=text("now()"))
    locked_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()


class Thread(Base):
    __tablename__ = "threads"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = _created()


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (CheckConstraint("status IN ('answered','refused')", name="status"),)
    id: Mapped[uuid.UUID] = _pk()
    thread_id: Mapped[uuid.UUID] = _fk("threads.id")
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    question: Mapped[str] = mapped_column(Text)
    answer_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10))
    retrieved_chunk_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), default=list)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    latency_ms_by_stage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = _created()


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (CheckConstraint("rating IN (-1, 1)", name="rating"),)
    id: Mapped[uuid.UUID] = _pk()
    answer_id: Mapped[uuid.UUID] = _fk("answers.id")
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()


class GoldenQuestion(Base):
    __tablename__ = "golden_questions"
    __table_args__ = (CheckConstraint("source IN ('manual','feedback')", name="source"),)
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    question: Mapped[str] = mapped_column(Text)
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Quotes, not chunk ids: chunk ids change whenever the chunker changes, quotes do not.
    expected_quotes: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    answerable: Mapped[bool] = mapped_column(Boolean, default=True)
    ask_as: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="manual")
    feedback_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, unique=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (CheckConstraint("status IN ('queued','running','done','failed')", name="status"),)
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    name: Mapped[str] = mapped_column(String(100))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10), default="queued")
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = _fk("users.id", ondelete="SET NULL", nullable=True)
    created_at: Mapped[datetime] = _created()


class EvalItem(Base):
    __tablename__ = "eval_items"
    id: Mapped[uuid.UUID] = _pk()
    eval_run_id: Mapped[uuid.UUID] = _fk("eval_runs.id")
    golden_question_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    question: Mapped[str] = mapped_column(Text)
    answerable: Mapped[bool] = mapped_column(Boolean)
    answer_status: Mapped[str] = mapped_column(String(10))
    hit_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrieved_chunk_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), default=list)
    answer_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


__all__ = [
    "Answer",
    "Chunk",
    "Collection",
    "CollectionGroup",
    "Document",
    "EvalItem",
    "EvalRun",
    "Feedback",
    "GoldenQuestion",
    "Group",
    "GroupMember",
    "Job",
    "Membership",
    "Thread",
    "User",
    "Workspace",
]
