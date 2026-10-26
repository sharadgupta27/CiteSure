"""Plan layout is computed from document structure only (no model): splitting, effort, ordering, weeks."""

from __future__ import annotations

import uuid

from app.repositories.learning_sources import ChunkMeta
from app.services.learning import layout

DOC = uuid.uuid4()


def make_chunks(sections: list[tuple[str, int]], tokens: int = 400) -> list[ChunkMeta]:
    """`sections` = (heading, number of chunks); one page per chunk."""
    chunks: list[ChunkMeta] = []
    for heading, count in sections:
        for _ in range(count):
            n = len(chunks)
            chunks.append(ChunkMeta(uuid.uuid4(), DOC, n, ["Title", heading], n + 1, n + 1, tokens))
    return chunks


def test_minutes_are_words_over_reading_speed_and_at_least_one() -> None:
    assert layout.minutes_for_tokens(400, 200) == 2  # 400 tokens = 300 words = 1.5 min -> 2
    assert layout.minutes_for_tokens(1, 200) == 1
    assert layout.minutes_for_tokens(4000, 100) == 30


def test_spread_samples_evenly_and_keeps_order() -> None:
    assert layout.spread(list(range(10)), 4) == [0, 3, 6, 9]
    assert layout.spread(list(range(3)), 10) == [0, 1, 2]
    assert layout.spread(list(range(10)), 1) == [0]
    assert layout.spread([], 3) == []
    assert layout.spread([1, 2], 0) == []


def test_a_short_document_is_a_single_unit() -> None:
    units = layout.split_units(make_chunks([("A", 2)]), words_per_minute=200, unit_minutes=30, max_units=12)
    assert len(units) == 1
    assert units[0].page_start == 1 and units[0].page_end == 2
    assert units[0].ord_start == 0 and units[0].ord_end == 1
    assert units[0].label == "A"


def test_units_cover_every_chunk_once_in_order() -> None:
    chunks = make_chunks([("Intro", 4), ("Method", 6), ("Results", 5), ("Discussion", 5)])
    units = layout.split_units(chunks, words_per_minute=200, unit_minutes=10, max_units=12)
    assert len(units) > 1
    flat = [cid for u in units for cid in u.chunk_ids]
    assert flat == [c.chunk_id for c in chunks]
    assert all(u.chunk_ids for u in units)
    assert sum(u.minutes for u in units) >= layout.minutes_for_tokens(400 * 20, 200) - len(units)  # rounding only


def test_cuts_prefer_heading_boundaries() -> None:
    chunks = make_chunks([("Intro", 5), ("Method", 5)])
    units = layout.split_units(chunks, words_per_minute=200, unit_minutes=10, max_units=2)
    assert [len(u.chunk_ids) for u in units] == [5, 5]
    assert units[0].label == "Intro" and units[1].label == "Method"


def test_cut_falls_back_to_an_even_split_without_headings() -> None:
    chunks = [ChunkMeta(uuid.uuid4(), DOC, i, [], None, None, 400) for i in range(10)]
    units = layout.split_units(chunks, words_per_minute=200, unit_minutes=10, max_units=2)
    assert [len(u.chunk_ids) for u in units] == [5, 5]
    assert units[0].page_start is None and units[0].label == ""


def test_unit_count_is_capped() -> None:
    chunks = make_chunks([("A", 30)])
    assert len(layout.split_units(chunks, words_per_minute=200, unit_minutes=5, max_units=3)) == 3
    assert len(layout.split_units(chunks[:2], words_per_minute=200, unit_minutes=5, max_units=50)) <= 2


def test_empty_document_has_no_units() -> None:
    assert layout.split_units([], words_per_minute=200, unit_minutes=30, max_units=12) == []


def test_long_label_is_shortened() -> None:
    chunks = make_chunks([("One", 1), ("Two", 1), ("Three", 1), ("Four", 1)])
    unit = layout.split_units(chunks, words_per_minute=200, unit_minutes=240, max_units=1)[0]
    assert unit.label == "One; Two; Three ..."


def test_introductions_come_first_then_relevance() -> None:
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    order = layout.order_by_topic(
        [(a, "Advanced topics", 0.9), (b, "A survey of methods", 0.2), (c, "Case study", 0.5), (d, "Introduction", 0.1)]
    )
    assert order == [b, d, a, c]  # the two introductory titles first (relevance breaks that tie), then by relevance


def test_weeks_fill_up_and_never_split_a_step() -> None:
    assert layout.assign_weeks([60, 60, 60, 60, 60], hours_per_week=2) == [1, 1, 2, 2, 3]
    assert layout.assign_weeks([300], hours_per_week=1) == [1]  # longer than a week: still one step in week 1
    assert layout.assign_weeks([300, 10], hours_per_week=1) == [1, 2]
    assert layout.assign_weeks([], hours_per_week=4) == []


def test_unit_chunks_without_topic_are_an_even_sample() -> None:
    ids = [uuid.uuid4() for _ in range(10)]
    picked = layout.pick_unit_chunks(ids, None, 3)
    assert len(picked) == 3 and picked[0] == ids[0] and picked[-1] == ids[9]


def test_unit_chunks_with_topic_are_the_best_ranked_inside_the_unit() -> None:
    ids = [uuid.uuid4() for _ in range(6)]
    unit = ids[:3]
    ranked = [ids[5], ids[2], ids[4], ids[0]]
    assert layout.pick_unit_chunks(unit, ranked, 5) == [ids[2], ids[0]]
    assert layout.pick_unit_chunks(unit, [ids[5]], 5) == []  # nothing relevant here: not padded with unrelated text
