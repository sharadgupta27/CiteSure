"""Pydantic models for the phase 2 endpoints (annotations and the watched-folder inbox). Names and fields mirror
components.schemas in openapi.yaml; tests/unit/test_contract.py fails when they drift apart."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.api import ApiModel

AnnotationColor = Literal["yellow", "green", "blue", "pink", "orange"]
InboxItemStatus = Literal["imported", "duplicate", "quarantined", "failed"]

_EDGE_TOLERANCE = 0.001  # browsers report sub-pixel rects that overshoot the page box by a hair


class NormalizedRect(ApiModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(ge=0, le=1)
    h: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _inside_the_page(self) -> NormalizedRect:
        if self.x + self.w > 1 + _EDGE_TOLERANCE or self.y + self.h > 1 + _EDGE_TOLERANCE:
            raise ValueError("A rectangle must lie inside the page")
        return self


class Annotation(ApiModel):
    id: uuid.UUID
    document_id: uuid.UUID
    page: int = Field(ge=1)
    rects: list[NormalizedRect]
    text: str
    note: str
    color: AnnotationColor
    created_at: datetime
    updated_at: datetime


class AnnotationCreate(ApiModel):
    page: int = Field(ge=1)
    rects: list[NormalizedRect] = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    note: str = Field("", max_length=2000)
    color: AnnotationColor = "yellow"


class AnnotationUpdate(ApiModel):
    note: str | None = Field(None, max_length=2000)
    color: AnnotationColor | None = None


class InboxItem(ApiModel):
    id: uuid.UUID
    folder: str
    filename: str
    size_bytes: int
    status: InboxItemStatus
    reason: str | None
    collection_id: uuid.UUID | None
    collection_name: str | None
    document_id: uuid.UUID | None
    document_status: str | None
    created_at: datetime


class InboxFolder(ApiModel):
    folder: str
    collection_id: uuid.UUID | None
    collection_name: str | None
    matched: bool
    imported: int
    duplicates: int
    quarantined: int
    failed: int
    last_activity_at: datetime | None


class InboxStatus(ApiModel):
    enabled: bool
    workspace_folder: str
    poll_seconds: int
    max_file_mb: int
    allowed_types: list[str]
    last_scan_at: datetime | None
    scan_requested: bool
    folders: list[InboxFolder]
