"""Pydantic models for open-access full text. Names and fields mirror components.schemas in openapi.yaml."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from app.schemas.api import ApiModel, EgressRecord

FullTextRequestStatus = Literal["queued", "running", "ready", "failed"]


class FullTextFetchRequest(ApiModel):
    workspace_id: uuid.UUID
    url: str = Field(min_length=8, max_length=2000)
    doi: str | None = Field(default=None, max_length=300)


class FullTextStatus(ApiModel):
    id: uuid.UUID
    status: FullTextRequestStatus
    title: str | None
    passages: int | None
    pages: int | None
    cached: bool
    error: str | None  # a reason code: unsupported_source, no_open_access, host_not_allowed, too_large, ...
    message: str | None  # what to tell the user about the error
    fetches_remaining: int
    egress: list[EgressRecord]
