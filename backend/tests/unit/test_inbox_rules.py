"""The inbox's path rules and file-system safety, without a database."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas import viewer as v
from app.services import inbox
from app.worker import inbox_watcher

W1, W2, W3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
C1, C2 = uuid.uuid4(), uuid.uuid4()


def test_slugify() -> None:
    assert inbox.slugify("Acme Corp.") == "acme-corp"
    assert inbox.slugify("  --R&D / Materials--  ") == "r-d-materials"
    assert inbox.slugify("???") == ""


def test_workspace_folder_is_the_slug_only_when_it_is_unique() -> None:
    folders = inbox.workspace_folders([(W1, "Acme"), (W2, "ACME!"), (W3, "Beta Labs"), (uuid.uuid4(), "???")])
    assert folders[W1] == str(W1) and folders[W2] == str(W2)  # ambiguous: fall back to the id
    assert folders[W3] == "beta-labs"
    assert list(folders.values())[3] != ""  # nothing sluggable: the id again


def test_workspace_resolution_fails_closed() -> None:
    workspaces = [(W1, "Acme"), (W2, "Acme"), (W3, "Beta Labs")]
    assert inbox.resolve_workspace("beta-labs", workspaces).id == W3
    assert inbox.resolve_workspace("Beta Labs", workspaces).id == W3
    assert inbox.resolve_workspace(str(W1), workspaces).id == W1  # an id always works, even when names collide
    ambiguous = inbox.resolve_workspace("acme", workspaces)
    assert ambiguous.id is None and "more than one" in (ambiguous.reason or "").lower()
    assert inbox.resolve_workspace("nope", workspaces).id is None
    assert inbox.resolve_workspace(str(uuid.uuid4()), workspaces).id is None
    assert inbox.resolve_workspace("---", workspaces).id is None  # an empty slug must not match an empty slug


def test_collection_resolution_fails_closed() -> None:
    collections = [(C1, "HR Policies"), (C2, "Finance")]
    assert inbox.resolve_collection("HR Policies", collections).id == C1
    assert inbox.resolve_collection("hr policies", collections).id == C1
    assert inbox.resolve_collection("hr-policies", collections).id == C1
    assert inbox.resolve_collection("Legal", collections).id is None
    assert inbox.resolve_collection("..", collections).id is None
    same = [(C1, "Policies"), (C2, "policies")]
    assert inbox.resolve_collection("POLICIES", same).id is None  # two collections differ only by case: refuse to guess


def test_allowed_types_cannot_be_widened_by_a_typo() -> None:
    assert inbox.allowed_kinds(Settings(inbox_allowed_types="pdf, docx ,exe,pdf")) == ["pdf", "docx"]
    assert inbox.allowed_kinds(Settings(inbox_allowed_types="")) == []


@pytest.mark.parametrize(
    ("name", "noise"),
    [(".DS_Store", True), ("~$draft.docx", True), ("a.pdf.part", True), ("Thumbs.db", True), ("report.pdf", False)],
)
def test_noise_files(name: str, noise: bool) -> None:
    assert inbox.is_noise(name) is noise


def test_viewer_schemas_reject_bad_rectangles() -> None:
    with pytest.raises(ValidationError):
        v.NormalizedRect(x=0.8, y=0.1, w=0.5, h=0.1)
    with pytest.raises(ValidationError):
        v.NormalizedRect(x=-0.01, y=0.1, w=0.1, h=0.1)
    assert v.NormalizedRect(x=0.9, y=0.9, w=0.1005, h=0.1).w == pytest.approx(0.1005)  # sub-pixel overshoot tolerated
    with pytest.raises(ValidationError):
        v.AnnotationCreate(page=1, rects=[], text="x")


def test_walk_skips_hidden_folders_and_noise(tmp_path: Path) -> None:
    (tmp_path / "ws" / "col").mkdir(parents=True)
    (tmp_path / "ws" / "col" / "a.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "ws" / "col" / ".hidden.pdf").write_bytes(b"x")
    (tmp_path / "ws" / "col" / "b.pdf.part").write_bytes(b"x")
    (tmp_path / ".processed" / "ws" / "col").mkdir(parents=True)
    (tmp_path / ".processed" / "ws" / "col" / "old.pdf").write_bytes(b"x")
    (tmp_path / "loose.md").write_bytes(b"# hi")
    found = [c.parts for c in inbox_watcher.walk(tmp_path)]
    assert found == [("loose.md",), ("ws", "col", "a.pdf")]


def test_walk_reports_symlinks_without_following_them(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(b"%PDF-1.4 secret")
    root = tmp_path / "inbox"
    (root / "ws" / "col").mkdir(parents=True)
    try:
        os.symlink(outside / "secret.pdf", root / "ws" / "col" / "link.pdf")
        os.symlink(outside, root / "ws" / "dirlink", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available (Windows without developer mode)")
    found = {c.parts: c.is_symlink for c in inbox_watcher.walk(root)}
    assert found == {("ws", "col", "link.pdf"): True, ("ws", "dirlink"): True}  # nothing below the linked folder


def test_archive_moves_inside_the_root_and_never_overwrites(tmp_path: Path) -> None:
    (tmp_path / "ws" / "col").mkdir(parents=True)
    src = tmp_path / "ws" / "col" / "a.md"
    src.write_text("one")
    assert inbox_watcher.archive(tmp_path, ("ws", "col", "a.md"), ".processed")
    assert not src.exists() and (tmp_path / ".processed" / "ws" / "col" / "a.md").read_text() == "one"
    src.write_text("two")
    assert inbox_watcher.archive(tmp_path, ("ws", "col", "a.md"), ".processed")
    kept = sorted(p.name for p in (tmp_path / ".processed" / "ws" / "col").iterdir())
    assert len(kept) == 2 and "a.md" in kept  # the first copy is untouched; the second got a unique name


def test_archive_refuses_traversal(tmp_path: Path) -> None:
    root = tmp_path / "inbox"
    root.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    assert not inbox_watcher.archive(root, ("missing.md",), ".failed")
    # parts from a directory walk never contain separators, but a '..' component must still not escape the bucket
    assert not inbox_watcher.archive(root, ("..", "victim.txt"), ".failed")
    assert victim.read_text() == "keep me"


def test_archive_refuses_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "inbox"
    root.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    try:
        os.symlink(victim, root / "link.md")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available (Windows without developer mode)")
    assert not inbox_watcher.archive(root, ("link.md",), ".failed")
    assert (root / "link.md").is_symlink() and victim.read_text() == "keep me"


def test_read_refuses_a_path_that_leaves_the_root(tmp_path: Path) -> None:
    root = tmp_path / "inbox"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# outside")
    info = outside.stat()
    with pytest.raises(ValueError, match="outside"):
        inbox_watcher._read(root / ".." / "outside.md", info.st_size, info.st_mtime_ns, root.resolve(), 1000)


def test_read_notices_a_file_that_is_still_changing(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    target.write_text("# a")
    info = target.stat()
    assert inbox_watcher._read(target, info.st_size, info.st_mtime_ns, tmp_path.resolve(), 100) == b"# a"
    assert inbox_watcher._read(target, info.st_size + 1, info.st_mtime_ns, tmp_path.resolve(), 100) is None
    assert inbox_watcher._read(target, info.st_size, info.st_mtime_ns + 1, tmp_path.resolve(), 100) is None
