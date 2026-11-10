"""The sample company in examples/: its folders match what app.seed_example creates, and every file is one the inbox and
the upload endpoint accept and can parse."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.rag.parsing import detect, parse_document
from app.seed_example import COLLECTIONS, INBOX_FOLDER, MEMBERS
from app.services.inbox import KIND_EXTENSIONS, allowed_kinds

ROOT = Path(__file__).resolve().parents[3]
COMPANY = ROOT / "examples" / "inbox" / INBOX_FOLDER
FILES = sorted(p for p in COMPANY.rglob("*") if p.is_file())


def test_the_folders_are_the_workspace_and_its_collections() -> None:
    assert [p.name for p in (ROOT / "examples" / "inbox").iterdir() if p.is_dir()] == [INBOX_FOLDER]
    assert {p.name for p in COMPANY.iterdir() if p.is_dir()} == set(COLLECTIONS)
    assert all(f.parent.parent == COMPANY for f in FILES), "files sit directly in a collection folder"
    assert {f.parent.name for f in FILES} == set(COLLECTIONS), "every collection has documents"


def test_every_group_that_guards_a_collection_has_a_member() -> None:
    assert {g for g in COLLECTIONS.values() if g} <= {g for g in MEMBERS.values() if g}


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_each_file_is_accepted_by_the_default_inbox_and_parses(path: Path) -> None:
    data = path.read_bytes()
    kind = detect(data).kind
    assert kind in allowed_kinds(Settings(env="test")), f"{kind} is not in the default INBOX_ALLOWED_TYPES"
    assert path.suffix.lower() in KIND_EXTENSIONS[kind], "the extension must match the content"
    assert len(data) <= Settings(env="test").inbox_max_file_mb * 1024 * 1024
    text = " ".join(section.text for section in parse_document(kind, data, path.name).sections)
    assert "Fictional sample data" in text, "every sample says it is invented"
    assert len(text.split()) > 80


@pytest.mark.parametrize("compose_file", ["docker-compose.yml", "docker-compose.private.yml"])
def test_the_worker_can_mount_the_inbox_read_only(compose_file: str) -> None:
    worker = yaml.safe_load((ROOT / compose_file).read_text(encoding="utf-8"))["services"]["worker"]
    mounts = [str(v) for v in worker["volumes"] if ":/data/inbox" in str(v)]
    assert mounts == ["${INBOX_HOST_DIR:-./inbox}:/data/inbox:${INBOX_MOUNT_MODE:-rw}"]
