"""Phase 5 tables: the tamper-evident audit log and OIDC identities. Migration 0005 creates them.

`audit_log` is append-only. Each row stores the hash of the previous row (`prev_hash`) and its own `hash` over a
canonical encoding of its content, so editing, deleting or reordering a row breaks the chain from that row on
(`GET /workspaces/{id}/audit-events/verify`). The migration also installs triggers that make UPDATE, DELETE and
TRUNCATE fail at the database. Rows carry ids, counts and hashes only: never document text, question text or secrets.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TZDateTime, new_id, utcnow

GENESIS_HASH = "0" * 64  # `prev_hash` of the first row


class AuditEvent(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        UniqueConstraint("seq"),
        Index("ix_audit_log_workspace_seq", "workspace_id", "seq"),
        Index("ix_audit_log_actor_seq", "actor_id", "seq"),
        Index("ix_audit_log_action_seq", "action", "seq"),
        Index("ix_audit_log_created_at", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_id)
    seq: Mapped[int] = mapped_column(BigInteger)  # gap-free position in the chain, assigned under an advisory lock
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, server_default=text("now()"))
    # Plain columns, no foreign keys: the log must outlive the users, workspaces and documents it mentions.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str | None] = mapped_column(String(200), nullable=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class OidcIdentity(Base):
    """Links an identity-provider subject to a local user, so a later change of e-mail address does not orphan it."""

    __tablename__ = "oidc_identities"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    issuer: Mapped[str] = mapped_column(String(300))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, server_default=text("now()"))
    last_login_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, server_default=text("now()"))


class OidcGroupGrant(Base):
    """A group membership that the identity provider granted (as opposed to one an admin added by hand).
    Only these are revoked when the provider's groups claim stops listing the group."""

    __tablename__ = "oidc_group_grants"
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
