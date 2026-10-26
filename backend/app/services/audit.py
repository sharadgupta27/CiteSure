"""Tamper-evident audit log.

Other code calls `record(...)` (or the request-scoped `AuditLog.record`) to append one row. Every row stores the hash
of the row before it and its own hash over a canonical encoding of its content, so changing, removing or reordering a
row is detected by `verify_chain` from that row on. The table is also append-only at the database (migration 0005).

What goes into an entry is limited on purpose: ids, counts, lengths, hashes, enum-like labels. Never document text,
question text or secrets. `sanitize_metadata` enforces that for callers that forget: forbidden keys are dropped, long
strings are cut.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.base import utcnow
from app.models.security import GENESIS_HASH, AuditEvent

log = logging.getLogger("citesure.audit")

# Chain appends are serialised with a transaction-scoped advisory lock (any constant; unique to this feature).
_CHAIN_LOCK = 0x43495445_41554449  # "CITE" "AUDI"

# Action names. Stable strings: they are stored, filtered on and exported.
LOGIN = "auth.login"
LOGIN_FAILED = "auth.login_failed"
REGISTER = "auth.register"
OIDC_LOGIN = "auth.oidc_login"
OIDC_FAILED = "auth.oidc_failed"
WORKSPACE_CREATE = "workspace.create"
MEMBER_ADD = "member.add"
GROUP_CREATE = "group.create"
GROUP_MEMBER_ADD = "group.member_add"
COLLECTION_CREATE = "collection.create"
COLLECTION_UPDATE = "collection.update"
COLLECTION_DELETE = "collection.delete"
DOCUMENT_UPLOAD = "document.upload"
DOCUMENT_DELETE = "document.delete"
DOCUMENT_REINDEX = "document.reindex"
ASK = "ask"
FEEDBACK_CREATE = "feedback.create"
GOLDEN_CREATE = "golden.create"
GOLDEN_UPDATE = "golden.update"
GOLDEN_DELETE = "golden.delete"
GOLDEN_PROMOTE = "golden.promote"
EVAL_RUN = "eval.run"
AUDIT_EXPORT = "audit.export"
AUDIT_VERIFY = "audit.verify"

# Keys that would carry content. They are dropped, whatever the caller passes.
_FORBIDDEN_KEYS = frozenset(
    {
        "text", "question", "query", "content", "body", "prompt", "answer", "quote", "comment", "snippet", "message",
        "password", "passwd", "secret", "token", "api_key", "apikey", "authorization", "cookie", "key", "email_text",
    }
)  # fmt: skip
_MAX_STRING = 200
_MAX_KEYS = 24
_MAX_DEPTH = 2


class Identity(Protocol):
    """Anything with an id and an e-mail address (a `schemas.api.User`, a `models.User`)."""

    id: uuid.UUID
    email: str


@dataclass(frozen=True)
class Actor:
    id: uuid.UUID | None
    email: str | None = None

    @classmethod
    def of(cls, who: Identity | Actor | None) -> Actor:
        if who is None:
            return cls(None, None)
        if isinstance(who, Actor):
            return who
        return cls(who.id, who.email)


def sha256_hex(value: str) -> str:
    """Hash of an identifier you must not store in the clear (for example an unknown e-mail on a failed login)."""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def sanitize_metadata(metadata: Mapping[str, Any] | None, _depth: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in list((metadata or {}).items())[:_MAX_KEYS]:
        name = str(key)[:60]
        if name.lower() in _FORBIDDEN_KEYS:
            log.warning("audit metadata key dropped (content-bearing name): %s", name)
            continue
        out[name] = _clean_value(value, _depth)
    return out


def _clean_value(value: Any, depth: int) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        return value if len(value) <= _MAX_STRING else value[:_MAX_STRING] + "…"
    if isinstance(value, Mapping):
        return sanitize_metadata(value, depth + 1) if depth < _MAX_DEPTH else "[nested]"
    if isinstance(value, list | tuple | set | frozenset):
        return [_clean_value(v, depth + 1) for v in list(value)[:50]]
    return str(value)[:_MAX_STRING]


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def compute_hash(
    prev_hash: str,
    *,
    seq: int,
    created_at: datetime,
    actor_id: uuid.UUID | None,
    actor_email: str | None,
    action: str,
    target: str | None,
    workspace_id: uuid.UUID | None,
    metadata: Mapping[str, Any],
) -> str:
    """SHA-256 over the previous hash and a canonical (sorted, compact, ASCII) JSON encoding of the row's content."""
    content = json.dumps(
        {
            "seq": seq,
            "created_at": _stamp(created_at),
            "actor_id": str(actor_id) if actor_id else None,
            "actor_email": actor_email,
            "action": action,
            "target": target,
            "workspace_id": str(workspace_id) if workspace_id else None,
            "metadata": metadata,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(prev_hash.encode() + b"\n" + content.encode()).hexdigest()


def row_hash(row: AuditEvent, prev_hash: str) -> str:
    return compute_hash(
        prev_hash,
        seq=row.seq,
        created_at=row.created_at,
        actor_id=row.actor_id,
        actor_email=row.actor_email,
        action=row.action,
        target=row.target,
        workspace_id=row.workspace_id,
        metadata=row.event_metadata,
    )


async def record(
    session: AsyncSession,
    actor: Identity | Actor | None,
    action: str,
    target: str | None = None,
    workspace_id: uuid.UUID | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> int:
    """Append one entry and return its sequence number.

    It commits in its own transaction on the same database, so the caller's transaction is left alone and a login
    failure (which ends in an exception and a rollback) is still recorded. Call it after the action succeeded, or
    for a failure you want to keep. Concurrent appends queue on an advisory lock so the chain never forks."""
    who = Actor.of(actor)
    clean = sanitize_metadata(metadata)
    if session.bind is None:
        raise RuntimeError("audit.record needs a session bound to an engine")
    factory = async_sessionmaker(bind=session.bind, expire_on_commit=False)
    async with factory() as own, own.begin():
        await own.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CHAIN_LOCK})
        last = (await own.execute(select(AuditEvent.seq, AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1))).first()
        seq, prev_hash = (last[0] + 1, last[1]) if last else (1, GENESIS_HASH)
        created_at = utcnow()  # Python and Postgres both keep microseconds, so the stored value hashes the same
        digest = compute_hash(
            prev_hash,
            seq=seq,
            created_at=created_at,
            actor_id=who.id,
            actor_email=who.email,
            action=action,
            target=target[:200] if target else None,
            workspace_id=workspace_id,
            metadata=clean,
        )
        own.add(
            AuditEvent(
                seq=seq,
                created_at=created_at,
                actor_id=who.id,
                actor_email=who.email,
                action=action,
                target=target[:200] if target else None,
                workspace_id=workspace_id,
                event_metadata=clean,
                prev_hash=prev_hash,
                hash=digest,
            )
        )
    return seq


class AuditLog:
    """`record` bound to a request's session, so route handlers only need `audit.record(user, action, ...)`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        actor: Identity | Actor | None,
        action: str,
        target: str | None = None,
        workspace_id: uuid.UUID | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> int:
        return await record(self.session, actor, action, target, workspace_id, metadata)

    async def workspace_of(self, kind: str, item_id: uuid.UUID) -> uuid.UUID | None:
        """The workspace a collection, document, answer or golden question belongs to (None if it does not exist).
        Server-side only: used to file an entry under the right workspace, never returned to the caller."""
        sql = _WORKSPACE_LOOKUPS.get(kind)
        if sql is None:
            raise ValueError(f"unknown kind: {kind}")
        found: uuid.UUID | None = (await self.session.execute(text(sql), {"id": item_id})).scalar_one_or_none()
        return found


_WORKSPACE_LOOKUPS = {
    "collection": "SELECT workspace_id FROM collections WHERE id = :id",
    "document": "SELECT c.workspace_id FROM documents d JOIN collections c ON c.id = d.collection_id WHERE d.id = :id",
    "answer": "SELECT workspace_id FROM answers WHERE id = :id",
    "golden": "SELECT workspace_id FROM golden_questions WHERE id = :id",
}


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    checked: int
    head_seq: int | None
    head_hash: str | None
    first_bad_seq: int | None
    reason: str | None
    starts_at_seq: int | None  # > 1 means older rows were removed by an operator (retention)


async def verify_chain(session: AsyncSession, batch: int = 1000) -> ChainReport:
    """Re-compute every hash in order. Stops at the first row that does not fit: a missing row (sequence gap), a row
    whose `prev_hash` is not the previous row's hash, or a row whose content no longer matches its `hash`.
    Removing the newest rows cannot be seen from the table alone: compare `head_hash` with a copy kept elsewhere."""
    checked = 0
    expected_prev: str | None = None
    last_seq = 0
    head_hash: str | None = None
    starts_at: int | None = None
    while True:
        rows = (
            (
                await session.execute(
                    select(AuditEvent).where(AuditEvent.seq > last_seq).order_by(AuditEvent.seq).limit(batch)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            break
        for row in rows:
            if starts_at is None:
                starts_at = row.seq
                if row.seq == 1 and row.prev_hash != GENESIS_HASH:
                    return _bad(checked, row.seq, "the first entry does not start from the genesis hash", starts_at)
                expected_prev = row.prev_hash  # after retention the oldest kept row is the trust anchor
            elif row.seq != last_seq + 1:
                return _bad(checked, row.seq, f"entries are missing before #{row.seq}", starts_at)
            if row.prev_hash != expected_prev:
                return _bad(checked, row.seq, "the link to the previous entry is broken", starts_at)
            if row_hash(row, row.prev_hash) != row.hash:
                return _bad(checked, row.seq, "the entry was changed after it was written", starts_at)
            expected_prev, head_hash, last_seq = row.hash, row.hash, row.seq
            checked += 1
    return ChainReport(True, checked, last_seq or None, head_hash, None, None, starts_at)


def _bad(checked: int, seq: int, reason: str, starts_at: int | None) -> ChainReport:
    return ChainReport(False, checked, None, None, seq, reason, starts_at)


CSV_COLUMNS = ("seq", "created_at", "actor_id", "actor_email", "action", "target", "workspace_id", "metadata", "hash")


def _csv_cell(value: str) -> str:
    """A cell that starts with = + - @ is read as a formula by spreadsheets; a leading quote defuses it."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def to_csv(rows: list[AuditEvent]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for r in rows:
        writer.writerow(
            [
                r.seq,
                _stamp(r.created_at),
                r.actor_id or "",
                _csv_cell(r.actor_email or ""),
                _csv_cell(r.action),
                _csv_cell(r.target or ""),
                r.workspace_id or "",
                _csv_cell(json.dumps(r.event_metadata, sort_keys=True, ensure_ascii=True)),
                r.hash,
            ]
        )
    return out.getvalue()
