"""Watched-folder ingestion, run inside the worker process (see services/inbox.py for the layout and the access rules).

Per file, in this order, and it fails closed at every step:
  symlink or odd file type  -> quarantined, left in place, never opened
  still being written       -> waited for (mtime newer than INBOX_SETTLE_SECONDS, or size/mtime changed while reading)
  no workspace/collection   -> quarantined (moved to <root>/.quarantine/), never imported with a guessed audience
  too big / wrong extension / content is not an allowed type (magic bytes, rag/parsing/detect.py) -> failed (.failed/)
  same sha256 already in the collection -> duplicate (.processed/)
  otherwise -> stored as a blob, a `documents` row (queued) and an ingestion job, exactly like an upload (.processed/)

Files that are moved out of the inbox cannot be seen again. If the move fails (read-only mount) the bookkeeping row
(path, size, mtime) still stops the file from being imported twice. Logs carry ids and counts only: no filenames, no text."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import stat
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePath

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.errors import UnsupportedMedia
from app.models.annotations import InboxItem
from app.providers import Providers
from app.rag.parsing import detect
from app.repositories import documents as documents_repo
from app.repositories import inbox as inbox_repo
from app.repositories import jobs as jobs_repo
from app.services.documents import INGEST_JOB, safe_filename
from app.services.inbox import (
    KIND_EXTENSIONS,
    allowed_kinds,
    is_noise,
    resolve_collection,
    resolve_workspace,
)

log = logging.getLogger("citesure.inbox")

PROCESSED, FAILED, QUARANTINE = ".processed", ".failed", ".quarantine"
MAX_DEPTH = 8
MAX_CANDIDATES = 5000  # a runaway tree must not turn one scan into an endless one
MAX_IMPORTS_PER_SCAN = 200  # the rest is picked up by the next scan
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


@dataclass(frozen=True)
class Candidate:
    parts: tuple[str, ...]  # path relative to the inbox root
    is_symlink: bool
    size: int
    mtime_ns: int


@dataclass
class ScanSummary:
    imported: int = 0
    duplicate: int = 0
    quarantined: int = 0
    failed: int = 0
    waiting: int = 0
    skipped: int = 0  # already handled in an earlier scan
    locked: bool = False  # another worker was scanning
    problem: str | None = None

    def counts(self) -> dict[str, int]:
        return {k: getattr(self, k) for k in ("imported", "duplicate", "quarantined", "failed", "waiting", "skipped")}


@dataclass
class _Context:
    root: Path
    root_real: Path
    settings: Settings
    providers: Providers
    sessionmaker: async_sessionmaker[AsyncSession]
    now: float
    workspaces: list[tuple[uuid.UUID, str]]
    kinds: list[str]
    extensions: frozenset[str]
    max_bytes: int
    collections: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = field(default_factory=dict)


def walk(root: Path) -> list[Candidate]:
    """Files below `root`, never following a symlink. Hidden folders (.processed, .failed, .quarantine) are skipped."""
    found: list[Candidate] = []
    stack: list[tuple[Path, tuple[str, ...]]] = [(root, ())]
    while stack and len(found) < MAX_CANDIDATES:
        directory, prefix = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith(".") or is_noise(entry.name):
                continue
            parts = (*prefix, entry.name)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISLNK(info.st_mode):
                found.append(Candidate(parts, True, 0, info.st_mtime_ns))
            elif stat.S_ISDIR(info.st_mode):
                if len(parts) < MAX_DEPTH:
                    stack.append((Path(entry.path), parts))
            elif stat.S_ISREG(info.st_mode):
                found.append(Candidate(parts, False, info.st_size, info.st_mtime_ns))
    return sorted(found, key=lambda c: c.parts)


def archive(root: Path, parts: tuple[str, ...], bucket: str) -> bool:
    """Move a regular file to <root>/<bucket>/<same relative path>. Never touches a symlink. False if it could not move."""
    try:
        src = root.joinpath(*parts)
        if not stat.S_ISREG(os.lstat(src).st_mode):
            return False
        target_dir = root.joinpath(bucket, *parts[:-1])
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / parts[-1]
        if target.exists():
            pure = PurePath(parts[-1])
            target = target_dir / f"{pure.stem}.{time.time_ns()}{pure.suffix}"
        if not target.resolve().is_relative_to(root.resolve() / bucket):
            return False
        os.replace(src, target)
    except OSError as exc:
        log.warning("inbox: could not move a file to %s (%s)", bucket, type(exc).__name__)
        return False
    return True


def _read(path: Path, expect_size: int, expect_mtime_ns: int, root_real: Path, limit: int) -> bytes | None:
    """The file's bytes, or None when it changed while we looked (still being copied). Raises OSError / ValueError."""
    if not path.resolve().is_relative_to(root_real):  # a junction or a parent symlink that points elsewhere
        raise ValueError("The path leads outside the inbox")
    fd = os.open(path, os.O_RDONLY | NOFOLLOW | getattr(os, "O_BINARY", 0))
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Not a regular file")
        if info.st_size != expect_size or info.st_mtime_ns != expect_mtime_ns:
            return None
        return handle.read(limit + 1)


async def _record(ctx: _Context, item: InboxItem, *, bucket: str | None, cand: Candidate, summary: ScanSummary) -> None:
    async with ctx.sessionmaker() as session:
        session.add(item)
        await session.commit()
    _count(summary, item.status)
    log.info("inbox: item id=%s status=%s", item.id, item.status)
    if bucket is not None:
        await asyncio.to_thread(archive, ctx.root, cand.parts, bucket)


def _count(summary: ScanSummary, status: str) -> None:
    setattr(summary, status, getattr(summary, status) + 1)


def _item(
    cand: Candidate, status: str, reason: str | None, ws: uuid.UUID | None, col: uuid.UUID | None, **kw: object
) -> InboxItem:
    return inbox_repo.new_item(
        workspace_id=ws,
        collection_id=col,
        source_key="/".join(cand.parts),
        folder="/".join(cand.parts[:-1]),
        filename=cand.parts[-1],
        size_bytes=cand.size,
        mtime_ns=cand.mtime_ns,
        status=status,
        reason=reason,
        **kw,  # type: ignore[arg-type]
    )


async def _collections(ctx: _Context, workspace_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    if workspace_id not in ctx.collections:
        async with ctx.sessionmaker() as session:
            ctx.collections[workspace_id] = await inbox_repo.collections_in(session, workspace_id)
    return ctx.collections[workspace_id]


async def _handle(ctx: _Context, cand: Candidate, summary: ScanSummary) -> None:
    async with ctx.sessionmaker() as session:
        if await inbox_repo.already_handled(session, "/".join(cand.parts), cand.size, cand.mtime_ns):
            summary.skipped += 1
            return

    ws_id: uuid.UUID | None = None
    col_id: uuid.UUID | None = None
    problem: str | None = None
    if len(cand.parts) < 2:
        problem = "Files must be placed in <workspace>/<collection>/ below the inbox root"
    else:
        resolved_ws = resolve_workspace(cand.parts[0], ctx.workspaces)
        ws_id, problem = resolved_ws.id, resolved_ws.reason
    if ws_id is not None and problem is None:
        if len(cand.parts) < 3:
            problem = "The file is not inside a collection folder"
        else:
            resolved = resolve_collection(cand.parts[1], await _collections(ctx, ws_id))
            col_id, problem = resolved.id, resolved.reason
        if problem is None and len(cand.parts) > 3:
            problem = "Folders inside a collection folder are not supported; put the file directly in the collection folder"

    if cand.is_symlink:
        await _record(
            ctx,
            _item(cand, "quarantined", "Symbolic links are not imported", ws_id, col_id),
            bucket=None,
            cand=cand,
            summary=summary,
        )
        return
    if ctx.now - cand.mtime_ns / 1e9 < ctx.settings.inbox_settle_seconds:
        summary.waiting += 1
        return
    if problem is not None or col_id is None or ws_id is None:
        item = _item(cand, "quarantined", problem or "No matching collection", ws_id, None)
        await _record(ctx, item, bucket=QUARANTINE, cand=cand, summary=summary)
        return

    failure = _precheck(ctx, cand)
    if failure:
        await _record(ctx, _item(cand, "failed", failure, ws_id, col_id), bucket=FAILED, cand=cand, summary=summary)
        return
    if summary.imported >= MAX_IMPORTS_PER_SCAN:
        summary.waiting += 1
        return

    path = ctx.root.joinpath(*cand.parts)
    try:
        data = await asyncio.to_thread(_read, path, cand.size, cand.mtime_ns, ctx.root_real, ctx.max_bytes)
    except ValueError as exc:
        await _record(ctx, _item(cand, "quarantined", str(exc), ws_id, col_id), bucket=None, cand=cand, summary=summary)
        return
    except OSError:
        await _record(
            ctx,
            _item(cand, "failed", "The file could not be read", ws_id, col_id),
            bucket=FAILED,
            cand=cand,
            summary=summary,
        )
        return
    if data is None:
        summary.waiting += 1
        return
    await _import(ctx, cand, data, ws_id, col_id, summary)


def _precheck(ctx: _Context, cand: Candidate) -> str | None:
    if cand.size == 0:
        return "The file is empty"
    if cand.size > ctx.max_bytes:
        return f"The file is larger than {ctx.settings.inbox_max_file_mb} MB"
    if PurePath(cand.parts[-1]).suffix.lower() not in ctx.extensions:
        return "This file type is not accepted here"
    return None


async def _import(
    ctx: _Context, cand: Candidate, data: bytes, ws_id: uuid.UUID, col_id: uuid.UUID, summary: ScanSummary
) -> None:
    ext = PurePath(cand.parts[-1]).suffix.lower()
    try:
        detected = detect(data)  # the content decides, never the name
    except UnsupportedMedia as exc:
        await _record(ctx, _item(cand, "failed", exc.detail, ws_id, col_id), bucket=FAILED, cand=cand, summary=summary)
        return
    if detected.kind not in ctx.kinds or ext not in KIND_EXTENSIONS[detected.kind]:
        reason = (
            "The content does not match the file name"
            if detected.kind in ctx.kinds
            else "This file type is not accepted here"
        )
        await _record(ctx, _item(cand, "failed", reason, ws_id, col_id), bucket=FAILED, cand=cand, summary=summary)
        return

    sha = hashlib.sha256(data).hexdigest()
    async with ctx.sessionmaker() as session:
        if await documents_repo.sha_exists(session, col_id, sha):
            duplicate = True
        else:
            duplicate = False
            blob_key = f"{ws_id}/{col_id}/{uuid.uuid4()}"
            await ctx.providers.blobs.put(blob_key, data)
            name = safe_filename(cand.parts[-1])
            try:
                doc = await documents_repo.create_document(
                    session,
                    collection_id=col_id,
                    title=PurePath(name).stem.replace("-", " ").replace("_", " "),
                    filename=name,
                    mime=detected.mime,
                    sha256=sha,
                    blob_key=blob_key,
                    uploaded_by=None,  # the watcher acts for the system; the collection's rules decide who can read it
                )
                await jobs_repo.enqueue(session, INGEST_JOB, {"document_id": str(doc.id)})
                item = _item(cand, "imported", None, ws_id, col_id, sha256=sha, document_id=doc.id)
                session.add(item)
                await session.commit()
            except IntegrityError:  # lost a race with an upload of the same file
                await session.rollback()
                await ctx.providers.blobs.delete(blob_key)
                duplicate = True
            except Exception:
                await session.rollback()
                await ctx.providers.blobs.delete(blob_key)
                raise
    if duplicate:
        item = _item(cand, "duplicate", "This file is already in the collection", ws_id, col_id, sha256=sha)
        await _record(ctx, item, bucket=PROCESSED, cand=cand, summary=summary)
        return
    summary.imported += 1
    log.info("inbox: item id=%s status=imported", item.id)
    await asyncio.to_thread(archive, ctx.root, cand.parts, PROCESSED)


async def scan_once(
    sessionmaker: async_sessionmaker[AsyncSession], providers: Providers, settings: Settings, *, now: float | None = None
) -> ScanSummary:
    """One pass over the inbox. Safe to call from several workers: only one scans at a time."""
    summary = ScanSummary()
    root = Path(settings.inbox_root)
    if not settings.inbox_root or not root.is_dir():
        summary.problem = "The inbox root is not set or is not a directory"
        return summary
    async with sessionmaker() as lock_session:
        if not await inbox_repo.try_scan_lock(lock_session):
            summary.locked = True
            return summary
        state = await inbox_repo.get_state(lock_session)
        requested_at: datetime | None = state.scan_requested_at if state else None
        async with sessionmaker() as session:
            workspaces = await inbox_repo.workspaces_for_worker(session)
        kinds = allowed_kinds(settings)
        ctx = _Context(
            root=root,
            root_real=root.resolve(),
            settings=settings,
            providers=providers,
            sessionmaker=sessionmaker,
            now=time.time() if now is None else now,
            workspaces=workspaces,
            kinds=kinds,
            extensions=frozenset().union(*(KIND_EXTENSIONS[k] for k in kinds)),
            max_bytes=settings.inbox_max_file_mb * 1024 * 1024,
        )
        for cand in await asyncio.to_thread(walk, root):
            try:
                await _handle(ctx, cand, summary)
            except Exception as exc:  # one bad file must never stop the scan
                log.warning("inbox: a file could not be processed (%s)", type(exc).__name__)
                summary.failed += 1
        async with sessionmaker() as session:
            await inbox_repo.finish_scan(session, requested_at, summary.counts())
            await session.commit()
        await lock_session.rollback()
    return summary


async def run_forever(sessionmaker: async_sessionmaker[AsyncSession], providers: Providers, settings: Settings) -> None:
    """Scan every INBOX_POLL_SECONDS, and as soon as an admin asks for a scan. Returns at once when INBOX_ROOT is empty."""
    if not settings.inbox_root:
        log.info("inbox disabled (INBOX_ROOT is empty)")
        return
    log.info("inbox watching, poll=%ss", settings.inbox_poll_seconds)
    last = float("-inf")
    while True:
        try:
            async with sessionmaker() as session:
                state = await inbox_repo.get_state(session)
                requested = bool(state and state.scan_requested_at)
            elapsed = time.monotonic() - last
            if (requested and elapsed >= 2.0) or elapsed >= settings.inbox_poll_seconds:
                summary = await scan_once(sessionmaker, providers, settings)
                last = time.monotonic()
                if summary.problem:
                    log.warning("inbox scan skipped: %s", summary.problem)
                elif not summary.locked and any(summary.counts().values()):
                    log.info("inbox scan: %s", summary.counts())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("inbox scan failed (%s)", type(exc).__name__)
        await asyncio.sleep(1.0)
