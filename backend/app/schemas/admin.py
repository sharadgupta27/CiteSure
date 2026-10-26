"""Pydantic models for the phase 5 endpoints (audit, dashboard, sign-in options). Names and fields mirror
components.schemas in openapi.yaml; tests/unit/test_contract.py fails when they drift apart."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from app.schemas.api import ApiModel


# --- audit --------------------------------------------------------------------------------
class AuditEvent(ApiModel):
    seq: int
    created_at: dt.datetime
    actor_id: uuid.UUID | None
    actor_email: str | None
    action: str
    target: str | None
    workspace_id: uuid.UUID | None
    metadata: dict[str, Any]
    hash: str


class AuditEventPage(ApiModel):
    items: list[AuditEvent]
    total: int
    limit: int
    offset: int


class AuditChainStatus(ApiModel):
    ok: bool
    checked: int
    head_seq: int | None
    head_hash: str | None
    first_bad_seq: int | None
    reason: str | None
    starts_at_seq: int | None


# --- dashboard ----------------------------------------------------------------------------
class DashboardDay(ApiModel):
    date: dt.date
    questions: int
    answered: int
    refused: int
    cost_usd: float


class DashboardQuestions(ApiModel):
    total: int
    answered: int
    refused: int
    refusal_rate: float
    claims_shown: int
    claims_dropped: int
    dropped_claim_rate: float


class DashboardLatency(ApiModel):
    p50_ms: float | None
    p95_ms: float | None


class DashboardCost(ApiModel):
    total_usd: float
    per_question_usd: float
    tokens_in: int
    tokens_out: int


class DashboardCount(ApiModel):
    label: str
    count: int


class DashboardDocuments(ApiModel):
    total: int
    chunks: int
    by_status: list[DashboardCount]


class IngestFailure(ApiModel):
    document_id: uuid.UUID
    title: str
    error: str | None
    created_at: dt.datetime


class DashboardIngest(ApiModel):
    failed_documents: int
    failed_jobs: int
    recent_failures: list[IngestFailure]


class DashboardEgress(ApiModel):
    destination: str
    status: str
    count: int


class DashboardFeedback(ApiModel):
    up: int
    down: int
    positive_ratio: float | None


class Dashboard(ApiModel):
    workspace_id: uuid.UUID
    days: int
    generated_at: dt.datetime
    questions: DashboardQuestions
    per_day: list[DashboardDay]
    latency: DashboardLatency
    cost: DashboardCost
    documents: DashboardDocuments
    ingest: DashboardIngest
    egress: list[DashboardEgress]
    feedback: DashboardFeedback


# --- sign-in options ----------------------------------------------------------------------
class AuthConfig(ApiModel):
    password_login: bool
    registration: bool
    oidc_enabled: bool
    oidc_provider_name: str | None
