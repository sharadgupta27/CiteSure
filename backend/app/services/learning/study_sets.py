"""Study sets: a user's own reading lists, with notes and a progress roll-up.

A study set is not an ACL `Collection` and grants nothing: adding a document needs read access to it, and a document
the owner can no longer read disappears from the set (and from its roll-up) until access returns."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import Conflict, InvalidInput, NotFound
from app.models import Document
from app.models.base import utcnow
from app.models.learning import ReadingProgress as ProgressRow
from app.models.learning import StudySet as SetRow
from app.models.learning import StudySetItem as ItemRow
from app.repositories import learning_progress as progress_repo
from app.repositories import learning_sets as sets_repo
from app.schemas import learning as s
from app.services import acl
from app.services.learning import access
from app.services.learning.progress import FINISHED_PERCENT

MAX_ITEMS_PER_SET = 200
MAX_SETS_PER_WORKSPACE = 100


def rollup(percents: list[float | None]) -> s.ProgressRollup:
    """`None` marks a document nobody has opened; it counts as 0%. Saved public papers are not passed in."""
    total = len(percents)
    started = sum(1 for p in percents if p is not None)
    finished = sum(1 for p in percents if p is not None and p >= FINISHED_PERCENT)
    mean = sum(p or 0.0 for p in percents) / total if total else 0.0
    return s.ProgressRollup(
        documents_total=total, documents_started=started, documents_finished=finished, percent=round(mean, 1)
    )


def to_item(row: ItemRow, document: Document | None, progress: ProgressRow | None) -> s.StudySetItem:
    is_document = row.kind == "document" and document is not None
    return s.StudySetItem(
        id=row.id,
        position=row.position,
        kind="document" if is_document else "reference",
        document_id=document.id if is_document and document is not None else None,
        title=document.title if is_document and document is not None else (row.ref_title or ""),
        url=None if is_document else row.ref_url,
        source=None if is_document else row.ref_source,
        note=row.note,
        page_count=document.page_count if is_document and document is not None else None,
        percent=(progress.percent if progress is not None else 0.0) if is_document else None,
        added_at=row.added_at,
    )


class StudySetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _owned(self, user_id: uuid.UUID, set_id: uuid.UUID) -> tuple[SetRow, acl.AccessContext]:
        row = await sets_repo.get_set(self.session, set_id, user_id)
        if row is None:
            raise NotFound("Study set not found")
        # A user who left the workspace sees nothing of it, including their own sets.
        return row, await acl.context_for_workspace(self.session, user_id, row.workspace_id)

    async def _views(self, user_id: uuid.UUID, rows: list[SetRow], context: acl.AccessContext) -> list[s.StudySetDetail]:
        items = await sets_repo.visible_items(
            self.session, [r.id for r in rows], allowed_collection_ids=context.allowed_collection_ids
        )
        document_ids = [d.id for _, d in items if d is not None]
        progress = await progress_repo.for_documents(self.session, user_id, document_ids)
        grouped: dict[uuid.UUID, list[s.StudySetItem]] = defaultdict(list)
        percents: dict[uuid.UUID, list[float | None]] = defaultdict(list)
        for item, document in items:
            row_progress = progress.get(document.id) if document is not None else None
            grouped[item.study_set_id].append(to_item(item, document, row_progress))
            if item.kind == "document" and document is not None:
                percents[item.study_set_id].append(row_progress.percent if row_progress is not None else None)
        return [
            s.StudySetDetail(
                id=r.id,
                workspace_id=r.workspace_id,
                name=r.name,
                description=r.description,
                notes=r.notes,
                item_count=len(grouped[r.id]),
                progress=rollup(percents[r.id]),
                created_at=r.created_at,
                updated_at=r.updated_at,
                items=grouped[r.id],
            )
            for r in rows
        ]

    async def list_sets(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> list[s.StudySet]:
        context = await acl.context_for_workspace(self.session, user_id, workspace_id)
        rows = list(await sets_repo.list_sets(self.session, user_id, workspace_id))
        # The list view leaves the items out: they are fetched with the set.
        return [
            s.StudySet.model_validate(v.model_dump(exclude={"items"})) for v in await self._views(user_id, rows, context)
        ]

    async def create(self, user_id: uuid.UUID, workspace_id: uuid.UUID, body: s.StudySetCreate) -> s.StudySetDetail:
        context = await acl.context_for_workspace(self.session, user_id, workspace_id)
        name = body.name.strip()
        if not name:
            raise InvalidInput("name: must not be blank")
        if await sets_repo.name_taken(self.session, user_id, workspace_id, name):
            raise Conflict("You already have a study set with this name")
        if len(await sets_repo.list_sets(self.session, user_id, workspace_id)) >= MAX_SETS_PER_WORKSPACE:
            raise InvalidInput(f"A workspace can hold at most {MAX_SETS_PER_WORKSPACE} study sets per user")
        row = await sets_repo.create_set(self.session, user_id, workspace_id, name, body.description.strip())
        await self.session.commit()
        return (await self._views(user_id, [row], context))[0]

    async def get(self, user_id: uuid.UUID, set_id: uuid.UUID) -> s.StudySetDetail:
        row, context = await self._owned(user_id, set_id)
        return (await self._views(user_id, [row], context))[0]

    async def update(self, user_id: uuid.UUID, set_id: uuid.UUID, body: s.StudySetUpdate) -> s.StudySetDetail:
        row, context = await self._owned(user_id, set_id)
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise InvalidInput("name: must not be blank")
            if await sets_repo.name_taken(self.session, user_id, row.workspace_id, name, except_id=row.id):
                raise Conflict("You already have a study set with this name")
            row.name = name
        if body.description is not None:
            row.description = body.description.strip()
        if body.notes is not None:
            row.notes = body.notes
        row.updated_at = utcnow()
        await self.session.commit()
        return (await self._views(user_id, [row], context))[0]

    async def delete(self, user_id: uuid.UUID, set_id: uuid.UUID) -> None:
        row, _ = await self._owned(user_id, set_id)
        await sets_repo.delete_set(self.session, row.id)
        await self.session.commit()

    # --- items ----------------------------------------------------------------------------
    async def add_item(self, user_id: uuid.UUID, set_id: uuid.UUID, body: s.StudySetItemCreate) -> s.StudySetItem:
        row, context = await self._owned(user_id, set_id)
        if len(await sets_repo.all_items(self.session, row.id)) >= MAX_ITEMS_PER_SET:
            raise InvalidInput(f"A study set can hold at most {MAX_ITEMS_PER_SET} items")
        document: Document | None = None
        if body.document_id is not None:
            # 404 (not 403) for a document the user may not read, exactly like fetching it directly.
            (document,) = await access.readable_documents(self.session, context, [body.document_id])
            if await sets_repo.item_exists_for_document(self.session, row.id, document.id):
                raise Conflict("This document is already in the study set")
            item = await sets_repo.add_item(
                self.session,
                row.id,
                kind="document",
                document_id=document.id,
                ref_title=None,
                ref_url=None,
                ref_source=None,
                note=body.note,
            )
        else:
            assert body.reference is not None  # the request model guarantees exactly one of the two
            item = await sets_repo.add_item(
                self.session,
                row.id,
                kind="reference",
                document_id=None,
                ref_title=body.reference.title.strip(),
                ref_url=body.reference.url,
                ref_source=body.reference.source,
                note=body.note,
            )
        await sets_repo.touch(self.session, row.id)
        await self.session.commit()
        progress = await progress_repo.for_documents(self.session, user_id, [document.id] if document else [])
        return to_item(item, document, progress.get(document.id) if document else None)

    async def update_item(
        self, user_id: uuid.UUID, set_id: uuid.UUID, item_id: uuid.UUID, body: s.StudySetItemUpdate
    ) -> s.StudySetItem:
        row, context = await self._owned(user_id, set_id)
        item = await sets_repo.get_item(self.session, row.id, item_id)
        if item is None:
            raise NotFound("Study set item not found")
        if body.note is not None:
            item.note = body.note
        if body.position is not None:
            ordered = [i for i in await sets_repo.all_items(self.session, row.id) if i.id != item.id]
            ordered.insert(min(body.position, len(ordered)), item)
            for index, moved in enumerate(ordered):
                moved.position = index
        await sets_repo.touch(self.session, row.id)
        await self.session.commit()
        view = await self._views(user_id, [row], context)
        for entry in view[0].items:
            if entry.id == item.id:
                return entry
        raise NotFound("Study set item not found")  # the item's document is no longer readable

    async def remove_item(self, user_id: uuid.UUID, set_id: uuid.UUID, item_id: uuid.UUID) -> None:
        row, _ = await self._owned(user_id, set_id)
        item = await sets_repo.get_item(self.session, row.id, item_id)
        if item is None:
            raise NotFound("Study set item not found")
        await sets_repo.delete_item(self.session, item.id)
        await sets_repo.touch(self.session, row.id)
        await self.session.commit()

    # --- used by the plan builder -------------------------------------------------------------
    async def readable_document_ids(
        self, user_id: uuid.UUID, set_id: uuid.UUID
    ) -> tuple[SetRow, acl.AccessContext, list[uuid.UUID]]:
        """The set's documents the owner may read right now, in set order."""
        row, context = await self._owned(user_id, set_id)
        items = await sets_repo.visible_items(self.session, [row.id], allowed_collection_ids=context.allowed_collection_ids)
        return row, context, [d.id for i, d in items if i.kind == "document" and d is not None]
