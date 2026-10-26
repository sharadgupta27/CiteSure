"""Phase 4 tables (the learning layer). Import `Base` from app.models.base; migration 0004 creates them.

Everything here belongs to one user: a row is only ever read or written together with `user_id`, so one person's
progress, study sets and plans are invisible to everyone else (admins included). Rows that point at documents
are shown only while the caller may still read the document. Generated text (plan objectives, summaries) is not
stored here: it lives in `answers`, so verification, the right-to-erase scrub and the ACL re-check apply to it."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TZDateTime, new_id, utcnow


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_id)


def _fk(target: str, *, ondelete: str = "CASCADE", nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable)


def _now() -> Mapped[datetime]:
    return mapped_column(TZDateTime, default=utcnow, server_default=text("now()"))


class ReadingProgress(Base):
    """Where one user is in one document. `pages_read` is the set of pages marked read (1-based)."""

    __tablename__ = "reading_progress"
    __table_args__ = (
        CheckConstraint("percent >= 0 AND percent <= 100", name="percent"),
        Index("ix_reading_progress_user_opened", "user_id", "last_opened_at"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    last_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages_read: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    percent: Mapped[float] = mapped_column(Float, default=0.0)
    last_opened_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class StudySet(Base):
    """A user's own reading list. Not the ACL `Collection`: a study set grants nobody access to anything."""

    __tablename__ = "study_sets"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id", "name"),)
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class StudySetItem(Base):
    """One entry of a study set: a workspace document, or a saved public paper kept by reference (title + link only;
    nothing is fetched, so it can never be summarised or planned)."""

    __tablename__ = "study_set_items"
    __table_args__ = (
        UniqueConstraint("study_set_id", "document_id"),
        CheckConstraint("kind IN ('document','reference')", name="kind"),
        CheckConstraint(
            "(kind = 'document' AND document_id IS NOT NULL)"
            " OR (kind = 'reference' AND ref_title IS NOT NULL AND ref_url IS NOT NULL)",
            name="shape",
        ),
        Index("ix_study_set_items_set_position", "study_set_id", "position"),
    )
    id: Mapped[uuid.UUID] = _pk()
    study_set_id: Mapped[uuid.UUID] = _fk("study_sets.id")
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))
    document_id: Mapped[uuid.UUID | None] = _fk("documents.id", nullable=True)
    ref_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ref_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    ref_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    added_at: Mapped[datetime] = _now()


class LearningPlan(Base):
    __tablename__ = "learning_plans"
    __table_args__ = (Index("ix_learning_plans_user_workspace", "user_id", "workspace_id", "created_at"),)
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    study_set_id: Mapped[uuid.UUID | None] = _fk("study_sets.id", ondelete="SET NULL", nullable=True)
    thread_id: Mapped[uuid.UUID | None] = _fk("threads.id", ondelete="SET NULL", nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str | None] = mapped_column(String(300), nullable=True)
    hours_per_week: Mapped[float] = mapped_column(Float, default=4.0)
    created_at: Mapped[datetime] = _now()


class PlanStep(Base):
    """One reading unit. Its title, pages and effort are structural facts computed from the document; the objective is
    an `answers` row produced by the generate-and-verify pipeline (`answer_id`), or null when nothing was supported."""

    __tablename__ = "learning_plan_steps"
    __table_args__ = (Index("ix_learning_plan_steps_plan_position", "plan_id", "position"),)
    id: Mapped[uuid.UUID] = _pk()
    plan_id: Mapped[uuid.UUID] = _fk("learning_plans.id")
    position: Mapped[int] = mapped_column(Integer)
    week: Mapped[int] = mapped_column(Integer, default=1)
    document_id: Mapped[uuid.UUID] = _fk("documents.id")
    label: Mapped[str] = mapped_column(String(300), default="")  # section heading(s) taken from the document
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ord_start: Mapped[int] = mapped_column(Integer)  # first and last chunk of the unit (chunk `ord`)
    ord_end: Mapped[int] = mapped_column(Integer)
    est_minutes: Mapped[int] = mapped_column(Integer)
    answer_id: Mapped[uuid.UUID | None] = _fk("answers.id", ondelete="SET NULL", nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


__all__ = ["LearningPlan", "PlanStep", "ReadingProgress", "StudySet", "StudySetItem"]
