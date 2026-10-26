"""Reading progress: where each user is in each document, and how much of it they have read."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.learning import ReadingProgress as ProgressRow
from app.repositories import learning_progress as progress_repo
from app.schemas import learning as s
from app.services import acl
from app.services.learning import access

FINISHED_PERCENT = 99.9  # float rounding: 9 of 9 pages is 100.0, but a client may send 99.99


def merge_progress(
    *,
    existing_pages: Iterable[int],
    existing_last_page: int | None,
    existing_percent: float,
    page_count: int | None,
    body: s.ReadingProgressUpdate,
) -> tuple[int | None, list[int], float]:
    """(last_page, pages_read, percent) after applying one update. Pure, so the rules are unit-tested.

    Pages only ever accumulate (reading a page twice does not unread it); resetting is a separate call. With a known
    page count the percent is pages read / pages, otherwise it is the furthest position the client reported."""
    pages = set(existing_pages) | set(body.pages_read)
    if body.page is not None and body.mark_read:
        pages.add(body.page)
    if page_count is not None:
        pages = {p for p in pages if p <= page_count}
    last_page = body.page if body.page is not None else existing_last_page
    if last_page is not None and page_count is not None:
        last_page = min(last_page, page_count)
    if page_count:
        percent = min(100.0, round(100.0 * len(pages) / page_count, 1))
    elif body.percent is not None:
        percent = max(existing_percent, body.percent)
    else:
        percent = existing_percent
    return last_page, sorted(pages), percent


def to_progress(document_id: uuid.UUID, row: ProgressRow | None) -> s.ReadingProgress:
    if row is None:
        return s.ReadingProgress(
            document_id=document_id, last_page=None, pages_read=[], percent=0.0, last_opened_at=None, updated_at=None
        )
    return s.ReadingProgress(
        document_id=row.document_id,
        last_page=row.last_page,
        pages_read=list(row.pages_read or []),
        percent=row.percent,
        last_opened_at=row.last_opened_at,
        updated_at=row.updated_at,
    )


class ProgressService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID, document_id: uuid.UUID) -> s.ReadingProgress:
        await access.readable_document(self.session, user_id, document_id)
        return to_progress(document_id, await progress_repo.get(self.session, user_id, document_id))

    async def update(self, user_id: uuid.UUID, document_id: uuid.UUID, body: s.ReadingProgressUpdate) -> s.ReadingProgress:
        document = await access.readable_document(self.session, user_id, document_id)
        now: datetime = utcnow()
        row = await progress_repo.get_for_update(self.session, user_id, document_id, now)
        row.last_page, row.pages_read, row.percent = merge_progress(
            existing_pages=row.pages_read or [],
            existing_last_page=row.last_page,
            existing_percent=row.percent,
            page_count=document.page_count,
            body=body,
        )
        row.last_opened_at = row.updated_at = now
        await self.session.commit()
        return to_progress(document_id, row)

    async def reset(self, user_id: uuid.UUID, document_id: uuid.UUID) -> None:
        await access.readable_document(self.session, user_id, document_id)
        await progress_repo.delete_for(self.session, user_id, document_id)
        await self.session.commit()

    async def list_recent(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> list[s.ReadingProgressItem]:
        context = await acl.context_for_workspace(self.session, user_id, workspace_id)
        rows = await progress_repo.list_for_user(
            self.session, user_id, allowed_collection_ids=context.allowed_collection_ids
        )
        return [
            s.ReadingProgressItem(
                document_id=doc.id,
                document_title=doc.title,
                page_count=doc.page_count,
                last_page=row.last_page,
                pages_read=list(row.pages_read or []),
                percent=row.percent,
                last_opened_at=row.last_opened_at,
            )
            for row, doc in rows
        ]
