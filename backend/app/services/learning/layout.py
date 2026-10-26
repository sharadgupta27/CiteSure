"""Pure functions that lay out a reading plan: how a document splits into reading units, how long they take, which
document comes first and which week a unit falls in. No database, no model: everything here is computed from the
structure of the documents (headings, pages, sizes), so none of it can be a hallucinated fact."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from app.repositories.learning_sources import ChunkMeta

WORDS_PER_TOKEN = 0.75
MAX_LABEL_CHARS = 300
MAX_LABEL_SECTIONS = 3
# Titles that usually mark introductory material: read these before the rest.
FOUNDATIONAL = re.compile(
    r"\b(review|survey|introduction|intro|overview|tutorial|primer|basics|getting started|101)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Unit:
    """A contiguous run of chunks of one document that makes one plan step."""

    document_id: uuid.UUID
    label: str
    page_start: int | None
    page_end: int | None
    ord_start: int
    ord_end: int
    chunk_ids: tuple[uuid.UUID, ...]
    minutes: int


def minutes_for_tokens(tokens: int, words_per_minute: int) -> int:
    return max(1, math.ceil(tokens * WORDS_PER_TOKEN / words_per_minute))


def spread[T](items: Sequence[T], n: int) -> list[T]:
    """`n` items evenly spaced over the sequence, first and last included, in order. Used to sample a long document."""
    if n <= 0 or not items:
        return []
    if len(items) <= n:
        return list(items)
    if n == 1:
        return [items[0]]
    indexes = sorted({round(i * (len(items) - 1) / (n - 1)) for i in range(n)})
    return [items[i] for i in indexes]


def _section_key(chunk: ChunkMeta) -> tuple[str, ...]:
    return tuple(chunk.heading_path[:2])


def _label(chunks: Sequence[ChunkMeta]) -> str:
    """Headings of the unit, taken from the document itself (never generated)."""
    names: list[str] = []
    previous: tuple[str, ...] | None = None
    for chunk in chunks:
        key = _section_key(chunk)
        if key != previous and chunk.heading_path and chunk.heading_path[-1] not in names:
            names.append(chunk.heading_path[-1])
        previous = key
    if not names:
        return ""
    shown = "; ".join(names[:MAX_LABEL_SECTIONS]) + (" ..." if len(names) > MAX_LABEL_SECTIONS else "")
    return shown[:MAX_LABEL_CHARS]


def _pages(chunks: Sequence[ChunkMeta]) -> tuple[int | None, int | None]:
    starts = [c.page_start for c in chunks if c.page_start is not None]
    ends = [c.page_end if c.page_end is not None else c.page_start for c in chunks]
    ends_known = [e for e in ends if e is not None]
    return (min(starts) if starts else None, max(ends_known) if ends_known else None)


def split_units(chunks: Sequence[ChunkMeta], *, words_per_minute: int, unit_minutes: int, max_units: int) -> list[Unit]:
    """Cut one document (chunks in reading order) into about `unit_minutes` of reading per unit, at most `max_units`.

    Cuts prefer a heading boundary near the ideal position, so a unit tends to be whole sections rather than an
    arbitrary slice."""
    if not chunks:
        return []
    tokens = [max(c.token_count, 1) for c in chunks]
    total = sum(tokens)
    total_minutes = minutes_for_tokens(total, words_per_minute)
    target = max(1, min(math.ceil(total_minutes / unit_minutes), max_units, len(chunks)))
    starts = [0]
    for t in tokens[:-1]:
        starts.append(starts[-1] + t)  # starts[i] = tokens before chunk i
    cuts: list[int] = []
    previous_cut = 0
    for j in range(1, target):
        ideal = total * j / target
        lowest, highest = previous_cut + 1, len(chunks) - (target - j)
        if lowest > highest:
            break
        nearest = min(range(lowest, highest + 1), key=lambda i: abs(starts[i] - ideal))
        boundaries = [i for i in range(lowest, highest + 1) if _section_key(chunks[i]) != _section_key(chunks[i - 1])]
        if boundaries:
            heading_cut = min(boundaries, key=lambda i: abs(starts[i] - ideal))
            if abs(starts[heading_cut] - ideal) <= total / target / 2:
                nearest = heading_cut
        cuts.append(nearest)
        previous_cut = nearest
    edges = [0, *cuts, len(chunks)]
    units: list[Unit] = []
    for begin, end in zip(edges, edges[1:], strict=False):
        part = chunks[begin:end]
        page_start, page_end = _pages(part)
        units.append(
            Unit(
                document_id=part[0].document_id,
                label=_label(part),
                page_start=page_start,
                page_end=page_end,
                ord_start=part[0].ord,
                ord_end=part[-1].ord,
                chunk_ids=tuple(c.chunk_id for c in part),
                minutes=minutes_for_tokens(sum(tokens[begin:end]), words_per_minute),
            )
        )
    return units


def is_foundational(title: str) -> bool:
    return bool(FOUNDATIONAL.search(title))


def order_by_topic(documents: Sequence[tuple[uuid.UUID, str, float]]) -> list[uuid.UUID]:
    """(id, title, relevance to the topic) -> ids: introductions first, then the most relevant, ties by title."""
    ranked = sorted(documents, key=lambda d: (not is_foundational(d[1]), -d[2], d[1].lower(), str(d[0])))
    return [d[0] for d in ranked]


def assign_weeks(minutes: Sequence[int], hours_per_week: float) -> list[int]:
    """Week number (from 1) of each step. A step is never split, so a long one can overfill its week."""
    capacity = hours_per_week * 60
    week, used = 1, 0
    weeks: list[int] = []
    for m in minutes:
        if used > 0 and used + m > capacity:
            week, used = week + 1, 0
        weeks.append(week)
        used += m
    return weeks


def pick_unit_chunks(
    unit_chunk_ids: Sequence[uuid.UUID], ranked_ids: Sequence[uuid.UUID] | None, limit: int
) -> list[uuid.UUID]:
    """Which chunks of a unit the model reads. With a topic: the unit's chunks that retrieval ranked highest for it
    (none is a legitimate outcome: the step is then refused, not padded). Without: an even sample of the unit."""
    if ranked_ids is None:
        return spread(unit_chunk_ids, limit)
    members = set(unit_chunk_ids)
    return [c for c in ranked_ids if c in members][:limit]
