"""Heading-aware chunker.

Rules (docs/rag-design.md explains why):
1. Never split inside a sentence (a sentence longer than 2x the target is the only exception).
2. Pack sentences up to ~target tokens, with ~overlap of the previous chunk repeated at the start
   so a fact at a chunk border is still found.
3. Prefer to end a chunk at a section (heading) boundary once the chunk is more than 60% full.
4. Every chunk is an exact slice of the document text, so `char_start:char_end` is always accurate
   and the citation viewer can highlight the right words.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.rag.parsing.types import Section
from app.rag.text import count_tokens, sentence_spans

SECTION_SEPARATOR = "\n\n"
SECTION_BREAK_FILL = 0.6


@dataclass(frozen=True)
class ChunkDraft:
    ord: int
    text: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int
    token_count: int


@dataclass(frozen=True)
class _Unit:
    start: int
    end: int
    section: int
    tokens: int
    starts_section: bool


def _split_long(text: str, start: int, end: int, limit: int) -> list[tuple[int, int]]:
    """Cut an overlong 'sentence' (a giant table row, minified code) at word boundaries."""
    pieces: list[tuple[int, int]] = []
    piece_start = start
    words = 0
    pos = start
    for word in text[start:end].split(" "):
        pos += len(word) + 1
        words += 1
        if words >= limit:
            pieces.append((piece_start, min(pos - 1, end)))
            piece_start = pos
            words = 0
    if piece_start < end:
        pieces.append((piece_start, end))
    return pieces


def _build_units(sections: list[Section], target: int) -> tuple[str, list[_Unit]]:
    document_text = ""
    units: list[_Unit] = []
    for index, section in enumerate(sections):
        offset = len(document_text)
        document_text += section.text + SECTION_SEPARATOR
        first = True
        for start, end in sentence_spans(section.text):
            tokens = count_tokens(section.text[start:end])
            spans = _split_long(section.text, start, end, target * 2) if tokens > target * 2 else [(start, end)]
            for s, e in spans:
                units.append(_Unit(offset + s, offset + e, index, count_tokens(section.text[s:e]), starts_section=first))
                first = False
    return document_text.rstrip("\n"), units


def chunk_sections(
    sections: list[Section], *, target_tokens: int = 400, overlap: float = 0.15
) -> tuple[str, list[ChunkDraft]]:
    """Returns the normalised document text and the chunks (slices of that text)."""
    document_text, units = _build_units(sections, target_tokens)
    chunks: list[ChunkDraft] = []
    n = len(units)
    s = 0
    main_start = 0  # first unit that is new content (not overlap carried from the previous chunk)
    while s < n:
        e = s
        used = 0
        while e < n:
            unit = units[e]
            if e > s:
                if used + unit.tokens > target_tokens:
                    break
                if e > main_start and unit.starts_section and used >= SECTION_BREAK_FILL * target_tokens:
                    break
            used += unit.tokens
            e += 1
        window = units[s:e]
        char_start, char_end = window[0].start, window[-1].end
        pages = [page for u in window if (page := sections[u.section].page) is not None]
        text = document_text[char_start:char_end]
        chunks.append(
            ChunkDraft(
                ord=len(chunks),
                text=text,
                heading_path=list(sections[units[main_start].section].heading_path),
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                char_start=char_start,
                char_end=char_end,
                token_count=count_tokens(text),
            )
        )
        if e >= n:
            break
        budget = overlap * target_tokens
        k = e
        carried = 0
        while k - 1 > s and carried + units[k - 1].tokens <= budget:
            k -= 1
            carried += units[k].tokens
        s = k
        main_start = e
    return document_text, chunks
