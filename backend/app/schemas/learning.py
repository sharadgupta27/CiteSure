"""Pydantic models for the learning layer. Names and fields mirror components.schemas in openapi.yaml."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from app.schemas.api import Answer, ApiModel

StudyItemKind = Literal["document", "reference"]
MAX_PAGES_PER_UPDATE = 5000


# --- reading progress ----------------------------------------------------------------------
class ReadingProgress(ApiModel):
    document_id: uuid.UUID
    last_page: int | None
    pages_read: list[int]
    percent: float
    last_opened_at: datetime | None  # null until the document has been opened at least once
    updated_at: datetime | None


class ReadingProgressUpdate(ApiModel):
    """Everything is optional: a viewer reports the page it is on, and says when that page counts as read."""

    page: int | None = Field(default=None, ge=1, le=100_000)
    mark_read: bool = False
    pages_read: list[int] = Field(default_factory=list, max_length=MAX_PAGES_PER_UPDATE)
    percent: float | None = Field(default=None, ge=0, le=100)  # for documents without pages (Markdown, HTML, DOCX)

    @field_validator("pages_read")
    @classmethod
    def _pages_positive(cls, pages: list[int]) -> list[int]:
        if any(p < 1 or p > 100_000 for p in pages):
            raise ValueError("pages are numbered from 1")
        return pages


class ReadingProgressItem(ApiModel):
    document_id: uuid.UUID
    document_title: str
    page_count: int | None
    last_page: int | None
    pages_read: list[int]
    percent: float
    last_opened_at: datetime


# --- study sets ----------------------------------------------------------------------------
class ProgressRollup(ApiModel):
    documents_total: int
    documents_started: int
    documents_finished: int
    percent: float


class StudySet(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str
    notes: str
    item_count: int
    progress: ProgressRollup
    created_at: datetime
    updated_at: datetime


class StudySetItem(ApiModel):
    id: uuid.UUID
    position: int
    kind: StudyItemKind
    document_id: uuid.UUID | None
    title: str
    url: str | None
    source: str | None
    note: str
    page_count: int | None
    percent: float | None  # reading progress of a document; null for a saved public paper
    added_at: datetime


class StudySetDetail(StudySet):
    items: list[StudySetItem]


class StudySetCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class StudySetUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=20_000)


class ReferenceInput(ApiModel):
    """A published paper kept by reference. Only the title and link are stored; nothing is fetched."""

    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=8, max_length=1000)
    source: str | None = Field(default=None, max_length=40)

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("must be an http(s) link")
        return value


class StudySetItemCreate(ApiModel):
    document_id: uuid.UUID | None = None
    reference: ReferenceInput | None = None
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.document_id is None) == (self.reference is None):
            raise ValueError("give either document_id or reference")
        return self


class StudySetItemUpdate(ApiModel):
    note: str | None = Field(default=None, max_length=2000)
    position: int | None = Field(default=None, ge=0)


# --- learning plans ------------------------------------------------------------------------
class PlanStep(ApiModel):
    id: uuid.UUID
    position: int
    week: int
    document_id: uuid.UUID
    document_title: str
    label: str  # section heading(s) of the document this step covers
    page_start: int | None
    page_end: int | None
    est_minutes: int
    done: bool
    done_at: datetime | None
    reading_percent: float
    objective: Answer | None  # verified claims about the section, or a refusal; null if it was never generated


class LearningPlanSummary(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    study_set_id: uuid.UUID | None
    title: str
    topic: str | None
    hours_per_week: float
    weeks: int
    total_minutes: int
    steps_done: int
    steps_total: int
    percent: float
    created_at: datetime


class LearningPlan(LearningPlanSummary):
    steps: list[PlanStep]


class LearningPlanCreate(ApiModel):
    title: str | None = Field(default=None, max_length=200)
    study_set_id: uuid.UUID | None = None
    topic: str | None = Field(default=None, min_length=3, max_length=300)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    hours_per_week: float = Field(default=4.0, gt=0, le=80)

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        if self.study_set_id is not None and self.document_ids:
            raise ValueError("give either study_set_id or document_ids, not both")
        if self.study_set_id is None and not self.document_ids:
            raise ValueError("give a study_set_id, or a topic with document_ids")
        return self


class PlanStepUpdate(ApiModel):
    done: bool


# --- summarize and compare agents ----------------------------------------------------------
class SummarizeRequest(ApiModel):
    document_id: uuid.UUID
    focus: str | None = Field(default=None, min_length=3, max_length=300)


class CompareRequest(ApiModel):
    document_ids: list[uuid.UUID] = Field(min_length=2, max_length=5)
    aspect: str = Field(min_length=3, max_length=300)


__all__ = [
    "Answer",
    "CompareRequest",
    "LearningPlan",
    "LearningPlanCreate",
    "LearningPlanSummary",
    "PlanStep",
    "PlanStepUpdate",
    "ProgressRollup",
    "ReadingProgress",
    "ReadingProgressItem",
    "ReadingProgressUpdate",
    "ReferenceInput",
    "StudySet",
    "StudySetCreate",
    "StudySetDetail",
    "StudySetItem",
    "StudySetItemCreate",
    "StudySetItemUpdate",
    "StudySetUpdate",
    "SummarizeRequest",
]
