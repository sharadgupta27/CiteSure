"""The audit log's pure parts: what may be stored, how rows are hashed, and the CSV export. The chain itself, the
append-only triggers and the routes are covered by tests/integration/test_audit_dashboard.py (they need Postgres)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.security import GENESIS_HASH, AuditEvent
from app.services import audit

T0 = datetime(2026, 10, 25, 12, 0, 0, 123456, tzinfo=UTC)


def make_row(seq: int, prev: str, **overrides: object) -> AuditEvent:
    fields: dict[str, object] = {
        "seq": seq,
        "created_at": T0 + timedelta(seconds=seq),
        "actor_id": uuid.UUID(int=7),
        "actor_email": "admin@acme.example",
        "action": audit.DOCUMENT_DELETE,
        "target": "document:abc",
        "workspace_id": uuid.UUID(int=9),
        "event_metadata": {"bytes": 10},
        "prev_hash": prev,
    }
    row = AuditEvent(**{**fields, **overrides})
    row.hash = audit.row_hash(row, prev)
    return row


def test_content_bearing_keys_are_dropped_and_logged() -> None:
    clean = audit.sanitize_metadata(
        {
            "question": "what is the salary of X?",
            "text": "secret words",
            "Password": "p",
            "token": "t",
            "question_length": 24,
            "rating": -1,
        }
    )
    assert clean == {"question_length": 24, "rating": -1}


def test_long_strings_are_cut_and_nesting_is_bounded() -> None:
    clean = audit.sanitize_metadata({"note": "x" * 1000, "a": {"b": {"c": {"d": 1}}}, "ids": [uuid.UUID(int=1)] * 100})
    assert len(clean["note"]) <= 201
    assert clean["a"]["b"]["c"] == "[nested]"
    assert len(clean["ids"]) == 50 and clean["ids"][0] == str(uuid.UUID(int=1))


def test_metadata_values_survive_a_json_round_trip_unchanged() -> None:
    """The stored value is what gets re-hashed on verification, so sanitising must be idempotent."""
    once = audit.sanitize_metadata({"f": 0.1 + 0.2, "ok": True, "none": None, "n": 3})
    assert audit.sanitize_metadata(once) == once


def test_the_hash_depends_on_every_field_and_on_the_previous_hash() -> None:
    base = make_row(1, GENESIS_HASH)
    variants = [
        make_row(1, GENESIS_HASH, action="document.upload"),
        make_row(1, GENESIS_HASH, target="document:other"),
        make_row(1, GENESIS_HASH, actor_email="evil@acme.example"),
        make_row(1, GENESIS_HASH, actor_id=uuid.UUID(int=8)),
        make_row(1, GENESIS_HASH, workspace_id=None),
        make_row(1, GENESIS_HASH, event_metadata={"bytes": 11}),
        make_row(1, GENESIS_HASH, created_at=T0 + timedelta(microseconds=1)),
        make_row(2, GENESIS_HASH, created_at=T0 + timedelta(seconds=1)),
        make_row(1, "1" * 64),
    ]
    assert len({base.hash, *(v.hash for v in variants)}) == len(variants) + 1
    assert make_row(1, GENESIS_HASH).hash == base.hash  # deterministic
    assert len(base.hash) == 64


def test_the_hash_does_not_depend_on_metadata_key_order_or_timezone_spelling() -> None:
    a = make_row(1, GENESIS_HASH, event_metadata={"a": 1, "b": 2})
    b = make_row(1, GENESIS_HASH, event_metadata={"b": 2, "a": 1})
    assert a.hash == b.hash
    from datetime import timezone

    c = make_row(1, GENESIS_HASH, created_at=(T0 + timedelta(seconds=1)).astimezone(timezone(timedelta(hours=5))))
    assert c.hash == make_row(1, GENESIS_HASH).hash


def test_changing_a_stored_row_no_longer_matches_its_hash() -> None:
    row = make_row(1, GENESIS_HASH)
    row.event_metadata = {"bytes": 999}
    assert audit.row_hash(row, row.prev_hash) != row.hash


def test_actor_accepts_users_actors_and_nothing() -> None:
    class User:
        id = uuid.UUID(int=3)
        email = "u@acme.example"

    assert audit.Actor.of(User()) == audit.Actor(uuid.UUID(int=3), "u@acme.example")
    assert audit.Actor.of(None) == audit.Actor(None, None)
    actor = audit.Actor(uuid.UUID(int=4))
    assert audit.Actor.of(actor) is actor


def test_unknown_addresses_are_hashed_case_insensitively() -> None:
    assert audit.sha256_hex(" Bob@Example.com ") == audit.sha256_hex("bob@example.com")
    assert "bob" not in audit.sha256_hex("bob@example.com")


def test_csv_defuses_spreadsheet_formulas_and_keeps_the_chain_columns() -> None:
    rows = [make_row(1, GENESIS_HASH, actor_email='=HYPERLINK("http://evil")', target="+cmd|' /C calc'!A0")]
    text = audit.to_csv(rows)
    header, line = text.strip().split("\n", 1)
    assert header.split(",") == list(audit.CSV_COLUMNS)
    assert "'=HYPERLINK" in line and "'+cmd" in line
    assert rows[0].hash in line and "2026-10-25T12:00:01.123456Z" in line


def test_forbidden_key_warning_names_the_key_but_not_the_value(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="citesure.audit"):
        audit.sanitize_metadata({"question": "very private words"})
    assert "question" in caplog.text and "very private words" not in caplog.text
