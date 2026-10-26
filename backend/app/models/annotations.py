"""Phase 2 tables. Import `Base` from app.models.base; migration 0002 creates them.

`annotations`: a user's own highlights and notes on a document page. Private to their author.
`inbox_items` / `inbox_state`: what the watched-folder importer did with each file and when it last ran.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TZDateTime, new_id, utcnow

ANNOTATION_COLORS = ("yellow", "green", "blue", "pink", "orange")
INBOX_STATUSES = ("imported", "duplicate", "quarantined", "failed")


def _created() -> Mapped[datetime]:
    return mapped_column(TZDateTime, default=utcnow, server_default=text("now()"))


class Annotation(Base):
    __tablename__ = "annotations"
    __table_args__ = (
        CheckConstraint("color IN ('yellow','green','blue','pink','orange')", name="color"),
        CheckConstraint("page >= 1", name="page"),
        Index("ix_annotations_document_user", "document_id", "user_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_id)
    # Deleting a document (or a user) deletes the highlights, and with them the document words they quote.
    document_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    page: Mapped[int] = mapped_column(Integer)
    # Normalised rectangles: [{x, y, w, h}] as fractions of the page box, so they survive zooming.
    rects: Mapped[list[dict[str, float]]] = mapped_column(JSONB)
    text: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    color: Mapped[str] = mapped_column(String(10), default="yellow", server_default="yellow")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class InboxItem(Base):
    """One file the watcher looked at. `source_key` + size + mtime make a re-scan skip what it already handled even when
    the file could not be moved out of the inbox (read-only mount)."""

    __tablename__ = "inbox_items"
    __table_args__ = (
        CheckConstraint("status IN ('imported','duplicate','quarantined','failed')", name="status"),
        Index("ix_inbox_items_workspace_created", "workspace_id", "created_at"),
        Index("ix_inbox_items_source", "source_key", "size_bytes", "mtime_ns"),
    )
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_id)
    # NULL when the first folder level matched no workspace. Such rows are never shown through the API.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("collections.id", ondelete="SET NULL"), nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    source_key: Mapped[str] = mapped_column(String(1000))  # path relative to the inbox root
    folder: Mapped[str] = mapped_column(String(600))
    filename: Mapped[str] = mapped_column(String(300))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(12))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()


class InboxState(Base):
    """A single row (id = 1): when the worker last scanned, and whether an admin asked for a scan."""

    __tablename__ = "inbox_state"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_scan_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    scan_requested_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    last_counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
