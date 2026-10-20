"""Chunker: exact offsets, sentence integrity, overlap, heading awareness (CLAUDE.md: offset tests are mandatory)."""

from __future__ import annotations

import re

import pytest

from app.rag.chunking import chunk_sections
from app.rag.parsing.types import Section
from app.rag.text import count_tokens


def make_sections(n_sections: int = 6, sentences_per_section: int = 8) -> list[Section]:
    sections = []
    for s in range(n_sections):
        text = " ".join(
            f"Section {s} sentence {i} talks about topic {s}{i} in some detail." for i in range(sentences_per_section)
        )
        sections.append(Section(heading_path=("Doc", f"Part {s}"), text=text))
    return sections


@pytest.mark.parametrize("target", [30, 60, 120, 400])
def test_every_chunk_is_an_exact_slice_of_the_document(target: int) -> None:
    sections = make_sections()
    document_text, chunks = chunk_sections(sections, target_tokens=target, overlap=0.15)
    assert chunks
    for chunk in chunks:
        assert document_text[chunk.char_start : chunk.char_end] == chunk.text
        assert 0 <= chunk.char_start < chunk.char_end <= len(document_text)


@pytest.mark.parametrize("target", [30, 60, 120])
def test_chunks_never_split_a_sentence(target: int) -> None:
    # In this fixture every sentence starts with "Section" and ends with ".", so a mid-sentence cut would show.
    _, chunks = chunk_sections(make_sections(), target_tokens=target)
    for chunk in chunks:
        assert chunk.text.startswith("Section")
        assert chunk.text.endswith(".")


def test_chunks_cover_the_whole_document_in_order() -> None:
    sections = make_sections()
    document_text, chunks = chunk_sections(sections, target_tokens=60)
    assert [c.ord for c in chunks] == list(range(len(chunks)))
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(document_text)
    for before, after in zip(chunks, chunks[1:], strict=False):
        assert after.char_start > before.char_start  # progress
        # no content is skipped: whatever lies between two chunks is only whitespace
        assert document_text[before.char_end : max(after.char_start, before.char_end)].strip() == ""


def test_overlap_repeats_the_tail_of_the_previous_chunk() -> None:
    _, chunks = chunk_sections(make_sections(1, 20), target_tokens=60, overlap=0.3)
    assert len(chunks) > 2
    overlaps = [after.char_start < before.char_end for before, after in zip(chunks, chunks[1:], strict=False)]
    assert any(overlaps)


def test_no_overlap_when_disabled() -> None:
    _, chunks = chunk_sections(make_sections(1, 20), target_tokens=60, overlap=0.0)
    for before, after in zip(chunks, chunks[1:], strict=False):
        assert after.char_start >= before.char_end


def test_chunk_size_is_close_to_target() -> None:
    _, chunks = chunk_sections(make_sections(4, 30), target_tokens=80)
    for chunk in chunks[:-1]:
        assert chunk.token_count <= 80 * 1.5


def test_heading_path_follows_the_first_new_section() -> None:
    sections = make_sections(3, 4)
    _, chunks = chunk_sections(sections, target_tokens=40)
    assert chunks[0].heading_path == ["Doc", "Part 0"]
    assert chunks[-1].heading_path[-1] in {"Part 1", "Part 2"}


def test_small_sections_are_packed_but_a_big_chunk_prefers_section_boundaries() -> None:
    sections = [
        Section(("Doc", f"S{i}"), f"Short fact number {i} is here. Another fact follows it for section {i}.")
        for i in range(10)
    ]
    _, chunks = chunk_sections(sections, target_tokens=50, overlap=0.0)
    assert len(chunks) > 1
    for chunk in chunks[:-1]:
        # without overlap, a chunk that ended early did so at a section start, so it ends with a full sentence
        assert chunk.text.rstrip().endswith(".")


def test_page_numbers_are_tracked_for_page_based_documents() -> None:
    sections = [
        Section((), f"Page {p} says something useful about topic {p}. And more words here for page {p}.", page=p)
        for p in (1, 2, 3)
    ]
    _, chunks = chunk_sections(sections, target_tokens=1000)
    assert len(chunks) == 1
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 3)
    _, small = chunk_sections(sections, target_tokens=20, overlap=0.0)
    assert [c.page_start for c in small][0] == 1
    assert max(c.page_end or 0 for c in small) == 3


def test_a_giant_sentence_is_split_at_word_boundaries_not_mid_word() -> None:
    giant = " ".join(f"word{i}" for i in range(500))
    _, chunks = chunk_sections([Section(("Doc",), giant)], target_tokens=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert all(re.fullmatch(r"word\d+", w) for w in chunk.text.split())


def test_empty_input_gives_no_chunks() -> None:
    assert chunk_sections([], target_tokens=100) == ("", [])


def test_token_count_matches_text() -> None:
    _, chunks = chunk_sections(make_sections(2, 5), target_tokens=40)
    for chunk in chunks:
        assert chunk.token_count == count_tokens(chunk.text)
