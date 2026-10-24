"""The guard's view of the company's documents, backed by the same Postgres the app uses.

Deliberately NOT access-controlled: the guard protects the whole company's text, not what one user may read, so it
checks every collection. It only ever returns a boolean or a list of names to the guard, never chunk text to a caller.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import ColumnElement, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Collection, Document, Workspace

PHRASE_BATCH = 40
NAME_CACHE_SECONDS = 60.0
_names_cache: tuple[float, list[str]] | None = None


def reset_name_cache() -> None:
    global _names_cache
    _names_cache = None


class SqlInternalCorpus:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def contains_any_phrase(self, phrases: list[list[str]]) -> bool:
        config: ColumnElement[Any] = literal_column("'english'::regconfig")
        for start in range(0, len(phrases), PHRASE_BATCH):
            batch = phrases[start : start + PHRASE_BATCH]
            conditions = [Chunk.tsv.op("@@")(func.phraseto_tsquery(config, " ".join(words))) for words in batch]
            found = await self._session.scalar(select(Chunk.id).where(or_(*conditions)).limit(1))
            if found is not None:
                return True
        return False

    async def names(self) -> list[str]:
        """Workspace, collection and document names. Cached briefly: the guard runs on every public question."""
        global _names_cache
        now = time.monotonic()
        if _names_cache is not None and now - _names_cache[0] < NAME_CACHE_SECONDS:
            return _names_cache[1]
        names: set[str] = set()
        for column in (Workspace.name, Collection.name, Document.title):
            rows = await self._session.scalars(select(column).distinct())
            names.update(n for n in rows if n)
        result = sorted(names)
        _names_cache = (now, result)
        return result
