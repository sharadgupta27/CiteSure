"""Pure rules of the learning layer: progress merging, roll-ups and request validation."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas import learning as s
from app.services.learning.progress import merge_progress
from app.services.learning.study_sets import rollup


def merge(
    body: s.ReadingProgressUpdate,
    *,
    pages: list[int] | None = None,
    last: int | None = None,
    percent: float = 0.0,
    count: int | None = 10,
) -> tuple[int | None, list[int], float]:
    return merge_progress(
        existing_pages=pages or [], existing_last_page=last, existing_percent=percent, page_count=count, body=body
    )


# --- progress ---------------------------------------------------------------------------------------
def test_opening_a_page_without_reading_it_moves_the_bookmark_only() -> None:
    assert merge(s.ReadingProgressUpdate(page=3)) == (3, [], 0.0)


def test_marking_read_adds_the_page_and_pages_accumulate() -> None:
    last, pages, percent = merge(s.ReadingProgressUpdate(page=2, mark_read=True))
    assert (last, pages, percent) == (2, [2], 10.0)
    last, pages, percent = merge(s.ReadingProgressUpdate(page=3, mark_read=True, pages_read=[1]), pages=pages, last=last)
    assert (last, pages, percent) == (3, [1, 2, 3], 30.0)


def test_reading_a_page_twice_does_not_double_count() -> None:
    _, pages, percent = merge(s.ReadingProgressUpdate(page=2, mark_read=True), pages=[2])
    assert pages == [2] and percent == 10.0


def test_pages_past_the_end_are_ignored_and_the_bookmark_is_clamped() -> None:
    last, pages, percent = merge(s.ReadingProgressUpdate(page=50, mark_read=True, pages_read=[99, 4]), count=10)
    assert last == 10 and pages == [4] and percent == 10.0


def test_all_pages_read_is_exactly_one_hundred_percent() -> None:
    _, _, percent = merge(s.ReadingProgressUpdate(pages_read=list(range(1, 11))))
    assert percent == 100.0


def test_update_without_a_page_keeps_the_bookmark() -> None:
    assert merge(s.ReadingProgressUpdate(), last=7, pages=[7], percent=10.0) == (7, [7], 10.0)


def test_documents_without_pages_use_the_furthest_reported_percent() -> None:
    assert merge(s.ReadingProgressUpdate(percent=40.0), count=None)[2] == 40.0
    assert merge(s.ReadingProgressUpdate(percent=20.0), count=None, percent=40.0)[2] == 40.0  # scrolling back up
    assert merge(s.ReadingProgressUpdate(percent=80.0), count=None, percent=40.0)[2] == 80.0


def test_update_validation() -> None:
    with pytest.raises(ValidationError):
        s.ReadingProgressUpdate(page=0)
    with pytest.raises(ValidationError):
        s.ReadingProgressUpdate(pages_read=[1, 0])
    with pytest.raises(ValidationError):
        s.ReadingProgressUpdate(percent=101)


# --- roll-up ----------------------------------------------------------------------------------------
def test_rollup_counts_unopened_documents_as_zero() -> None:
    result = rollup([100.0, 50.0, None, None])
    assert (result.documents_total, result.documents_started, result.documents_finished) == (4, 2, 1)
    assert result.percent == 37.5


def test_rollup_of_an_empty_set() -> None:
    result = rollup([])
    assert result.documents_total == 0 and result.percent == 0.0


# --- request validation -----------------------------------------------------------------------------
def test_study_set_item_needs_exactly_one_of_document_or_reference() -> None:
    reference = s.ReferenceInput(title="A paper", url="https://arxiv.org/abs/1234.5678")
    assert s.StudySetItemCreate(document_id=uuid.uuid4()).reference is None
    assert s.StudySetItemCreate(reference=reference).document_id is None
    with pytest.raises(ValidationError):
        s.StudySetItemCreate()
    with pytest.raises(ValidationError):
        s.StudySetItemCreate(document_id=uuid.uuid4(), reference=reference)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://example.com/x", "https://", "not a url", "data:text/html,hi"])
def test_references_accept_only_http_links(url: str) -> None:
    with pytest.raises(ValidationError):
        s.ReferenceInput(title="x", url=url)


def test_plan_needs_a_study_set_or_documents_not_both() -> None:
    assert s.LearningPlanCreate(study_set_id=uuid.uuid4()).hours_per_week == 4.0
    assert s.LearningPlanCreate(document_ids=[uuid.uuid4()], topic="vacation policy").topic == "vacation policy"
    with pytest.raises(ValidationError):
        s.LearningPlanCreate()
    with pytest.raises(ValidationError):
        s.LearningPlanCreate(study_set_id=uuid.uuid4(), document_ids=[uuid.uuid4()])
    with pytest.raises(ValidationError):
        s.LearningPlanCreate(document_ids=[uuid.uuid4()], hours_per_week=0)


def test_compare_needs_two_to_five_documents() -> None:
    ids = [uuid.uuid4() for _ in range(6)]
    with pytest.raises(ValidationError):
        s.CompareRequest(document_ids=ids[:1], aspect="retention")
    with pytest.raises(ValidationError):
        s.CompareRequest(document_ids=ids, aspect="retention")
    assert len(s.CompareRequest(document_ids=ids[:5], aspect="retention").document_ids) == 5
