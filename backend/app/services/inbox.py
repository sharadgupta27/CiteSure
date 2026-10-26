"""Watched-folder inbox: the rules that map a path to a collection, and the admin-facing status.

Layout under INBOX_ROOT:   <workspace folder>/<collection name>/<file>

The collection folder IS the access decision: a file imported from it becomes a document of that collection and gets that
collection's access rules (open to the workspace, or limited to its groups). Nothing is ever guessed. A folder that
matches no workspace or collection, or matches more than one, gets its files quarantined, never imported with a broader
audience. This module is pure rules plus the API-side service; the scanning itself is worker/inbox_watcher.py."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import Conflict
from app.repositories import inbox as inbox_repo
from app.schemas import viewer as v
from app.services import acl

# Detected kind (by magic bytes, rag/parsing/detect.py) -> filename extensions that may carry it.
KIND_EXTENSIONS: dict[str, frozenset[str]] = {
    "pdf": frozenset({".pdf"}),
    "docx": frozenset({".docx"}),
    "markdown": frozenset({".md", ".markdown", ".txt"}),
    "html": frozenset({".html", ".htm"}),
}
IGNORED_SUFFIXES = (".part", ".partial", ".tmp", ".crdownload", ".swp", ".lock")
IGNORED_NAMES = frozenset({"thumbs.db", "desktop.ini"})
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _NON_SLUG.sub("-", name.casefold()).strip("-")


def allowed_kinds(settings: Settings) -> list[str]:
    """INBOX_ALLOWED_TYPES, reduced to kinds the parsers know (a typo cannot widen what is accepted)."""
    wanted = [t.strip().lower() for t in settings.inbox_allowed_types.split(",") if t.strip()]
    return [t for t in dict.fromkeys(wanted) if t in KIND_EXTENSIONS]


def is_noise(name: str) -> bool:
    """Hidden files and the temporary files editors and browsers leave behind: not worth a quarantine entry."""
    lower = name.lower()
    return name.startswith((".", "~$")) or lower in IGNORED_NAMES or lower.endswith(IGNORED_SUFFIXES)


def workspace_folders(workspaces: Sequence[tuple[uuid.UUID, str]]) -> dict[uuid.UUID, str]:
    """The first-level folder for each workspace: its name as a slug when that is unique, otherwise its id."""
    slugs = [slugify(name) for _, name in workspaces]
    return {
        ws_id: slug if slug and slugs.count(slug) == 1 else str(ws_id)
        for (ws_id, _), slug in zip(workspaces, slugs, strict=True)
    }


@dataclass(frozen=True)
class Resolved:
    id: uuid.UUID | None
    reason: str | None = None


def resolve_workspace(segment: str, workspaces: Sequence[tuple[uuid.UUID, str]]) -> Resolved:
    try:
        wanted = uuid.UUID(segment)
    except ValueError:
        wanted = None
    if wanted is not None:
        return (
            Resolved(wanted)
            if any(ws_id == wanted for ws_id, _ in workspaces)
            else Resolved(None, "No workspace has this id")
        )
    matches = [ws_id for ws_id, name in workspaces if slugify(name) == slugify(segment) and slugify(segment)]
    if len(matches) == 1:
        return Resolved(matches[0])
    if not matches:
        return Resolved(None, "No workspace matches this folder name")
    return Resolved(None, "More than one workspace matches this folder name; use the workspace id as the folder name")


def resolve_collection(segment: str, collections: Sequence[tuple[uuid.UUID, str]]) -> Resolved:
    exact = [cid for cid, name in collections if name.casefold() == segment.casefold()]
    if len(exact) == 1:
        return Resolved(exact[0])
    if len(exact) > 1:
        return Resolved(None, "More than one collection has this name")
    slug = slugify(segment)
    loose = [cid for cid, name in collections if slug and slugify(name) == slug]
    if len(loose) == 1:
        return Resolved(loose[0])
    if not loose:
        return Resolved(None, "No collection in this workspace matches this folder name")
    return Resolved(None, "More than one collection matches this folder name")


def _folder(
    folder: str, collection_id: uuid.UUID | None, name: str | None, rows: Sequence[tuple[str, int, datetime | None]]
) -> v.InboxFolder:
    totals = {"imported": 0, "duplicate": 0, "quarantined": 0, "failed": 0}
    for status, n, _ in rows:
        totals[status] += n
    stamps = [m for _, _, m in rows if m is not None]
    return v.InboxFolder(
        folder=folder,
        collection_id=collection_id,
        collection_name=name,
        matched=collection_id is not None,
        imported=totals["imported"],
        duplicates=totals["duplicate"],
        quarantined=totals["quarantined"],
        failed=totals["failed"],
        last_activity_at=max(stamps) if stamps else None,
    )


class InboxService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _admin(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        await acl.require_admin(self.session, user_id, workspace_id)

    async def status(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> v.InboxStatus:
        await self._admin(user_id, workspace_id)
        return await self._status(workspace_id)

    async def _status(self, workspace_id: uuid.UUID) -> v.InboxStatus:
        workspaces = await inbox_repo.workspaces_for_worker(self.session)
        ws_folder = workspace_folders(workspaces)[workspace_id]
        collections = await inbox_repo.collections_in(self.session, workspace_id)
        counts = await inbox_repo.status_counts(self.session, workspace_id)
        state = await inbox_repo.get_state(self.session)

        folders = [
            _folder(
                f"{ws_folder}/{name}",
                collection_id,
                name,
                [(s, n, m) for c, _f, s, n, m in counts if c == collection_id],
            )
            for collection_id, name in collections
        ]
        # Folders that matched nothing: surfaced so an admin can fix the name (or create the collection).
        loose: dict[str, list[tuple[str, int, datetime | None]]] = {}
        for collection_id, folder, status, n, latest_at in counts:
            if collection_id is None:
                loose.setdefault(folder, []).append((status, n, latest_at))
        folders += [_folder(folder, None, None, rows) for folder, rows in sorted(loose.items())]
        return v.InboxStatus(
            enabled=bool(self.settings.inbox_root),
            workspace_folder=ws_folder,
            poll_seconds=self.settings.inbox_poll_seconds,
            max_file_mb=self.settings.inbox_max_file_mb,
            allowed_types=allowed_kinds(self.settings),
            last_scan_at=state.last_scan_at if state else None,
            scan_requested=bool(state and state.scan_requested_at),
            folders=folders,
        )

    async def items(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID, *, status: str | None, limit: int
    ) -> list[v.InboxItem]:
        await self._admin(user_id, workspace_id)
        rows = await inbox_repo.list_items(self.session, workspace_id, status=status, limit=limit)
        return [
            v.InboxItem(
                id=item.id,
                folder=item.folder,
                filename=item.filename,
                size_bytes=item.size_bytes,
                status=item.status,
                reason=item.reason,
                collection_id=item.collection_id,
                collection_name=collection_name,
                document_id=item.document_id,
                document_status=document_status,
                created_at=item.created_at,
            )
            for item, collection_name, document_status in rows
        ]

    async def request_scan(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> v.InboxStatus:
        await self._admin(user_id, workspace_id)
        if not self.settings.inbox_root:
            raise Conflict("The watched-folder inbox is not enabled on this server (INBOX_ROOT is empty)")
        await inbox_repo.request_scan(self.session)
        await self.session.commit()
        return await self._status(workspace_id)
