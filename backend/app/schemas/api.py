"""Pydantic models for the HTTP API. Names and fields mirror components.schemas in openapi.yaml;
tests/unit/test_contract.py fails when they drift apart."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["admin", "member"]
Visibility = Literal["workspace", "groups"]
DocumentStatus = Literal["queued", "parsing", "embedding", "ready", "failed"]
Entailment = Literal["supported", "partial", "unsupported"]
AnswerStatus = Literal["answered", "refused"]
EvalRunStatus = Literal["queued", "running", "done", "failed"]
GoldenSource = Literal["manual", "feedback"]
AskScope = Literal["internal", "public", "both"]
SourceType = Literal["internal", "public"]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Error(ApiModel):
    code: str
    detail: str


# --- auth ---------------------------------------------------------------------------------
class RegisterRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(ApiModel):
    email: EmailStr
    password: str


class User(ApiModel):
    id: uuid.UUID
    email: str  # validated on input (RegisterRequest); output never re-validates stored addresses
    created_at: datetime


class TokenResponse(ApiModel):
    access_token: str
    token_type: Literal["bearer"]
    user: User


# --- workspaces ---------------------------------------------------------------------------
class Workspace(ApiModel):
    id: uuid.UUID
    name: str
    role: Role
    created_at: datetime


class WorkspaceCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)


class Member(ApiModel):
    user_id: uuid.UUID
    email: str
    role: Role


class MemberAdd(ApiModel):
    email: EmailStr
    role: Role


class Group(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    member_ids: list[uuid.UUID]


class GroupCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)


class GroupMemberAdd(ApiModel):
    email: EmailStr


# --- collections and documents ------------------------------------------------------------
class Collection(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    visibility: Visibility
    group_ids: list[uuid.UUID]
    created_at: datetime


class CollectionCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    visibility: Visibility
    group_ids: list[uuid.UUID]


class CollectionUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    visibility: Visibility | None = None
    group_ids: list[uuid.UUID] | None = None


class Document(ApiModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    title: str
    filename: str
    mime: str
    sha256: str
    status: DocumentStatus
    page_count: int | None
    chunk_count: int
    error: str | None
    created_at: datetime


class Chunk(ApiModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    collection_id: uuid.UUID
    ord: int
    text: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int


# --- ask ----------------------------------------------------------------------------------
class PipelineConfig(ApiModel):
    retrieval_mode: Literal["vector", "hybrid"]
    rerank: bool
    candidate_k: int = Field(ge=1, le=100)
    top_k: int = Field(ge=1, le=20)


class AskRequest(ApiModel):
    workspace_id: uuid.UUID
    question: str = Field(min_length=3, max_length=1000)
    thread_id: uuid.UUID | None = None
    config: PipelineConfig | None = None
    scope: AskScope | None = None
    public_query: str | None = Field(default=None, max_length=300)


class EgressRecord(ApiModel):
    destination: str
    status: Literal["sent", "blocked", "failed"]
    query: str | None
    reason: str | None


class PublicResearchStatus(ApiModel):
    enabled: bool
    private_mode: bool
    default_scope: AskScope
    sources: list[str]
    hosted_model_for_public: bool


class PublicQueryPreviewRequest(ApiModel):
    question: str = Field(min_length=3, max_length=1000)
    query: str | None = Field(default=None, max_length=300)


class PublicQueryPreview(ApiModel):
    query: str
    allowed: bool
    reasons: list[str]
    explanation: str


class Citation(ApiModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    quote: str
    quote_start: int
    quote_end: int
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    source_type: SourceType = "internal"
    url: str | None = None


class Verification(ApiModel):
    quote_match: float = Field(ge=0, le=1)
    entailment: Entailment


class Claim(ApiModel):
    text: str
    citations: list[Citation]
    verified: bool
    verification: Verification


class ClosestSource(ApiModel):
    document_id: uuid.UUID
    document_title: str
    chunk_id: uuid.UUID


class Refusal(ApiModel):
    reason: Literal["no_sources", "no_supported_claims"]
    message: str
    closest_sources: list[ClosestSource]


class Answer(ApiModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    question: str
    status: AnswerStatus
    scope: AskScope
    notices: list[str]
    egress: list[EgressRecord]
    claims: list[Claim]
    refusal: Refusal | None
    dropped_claims: int
    latency_ms_by_stage: dict[str, float]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    created_at: datetime


class StreamEvent(ApiModel):
    event: Literal["stage", "token", "final", "error"]
    data: str | Answer | Error


class Thread(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    created_at: datetime


class ThreadDetail(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    created_at: datetime
    answers: list[Answer]


# --- feedback -----------------------------------------------------------------------------
class FeedbackCreate(ApiModel):
    rating: Literal[-1, 1]
    comment: str | None = Field(max_length=2000)


class Feedback(ApiModel):
    id: uuid.UUID
    answer_id: uuid.UUID
    user_id: uuid.UUID
    rating: Literal[-1, 1]
    comment: str | None
    created_at: datetime


class FeedbackItem(ApiModel):
    id: uuid.UUID
    answer_id: uuid.UUID
    user_id: uuid.UUID
    rating: Literal[-1, 1]
    comment: str | None
    created_at: datetime
    question: str
    answer_status: AnswerStatus
    promoted: bool


# --- evaluation ---------------------------------------------------------------------------
class ExpectedQuote(ApiModel):
    document: str
    quote: str


class GoldenQuestion(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    question: str
    expected_answer: str | None
    expected_quotes: list[ExpectedQuote]
    answerable: bool
    ask_as: str | None
    source: GoldenSource
    tags: list[str]
    reason: str
    created_at: datetime


class GoldenQuestionCreate(ApiModel):
    question: str = Field(min_length=3)
    expected_answer: str | None
    expected_quotes: list[ExpectedQuote]
    answerable: bool
    ask_as: str | None
    tags: list[str]
    reason: str = Field(min_length=3)


class GoldenQuestionUpdate(ApiModel):
    question: str | None = None
    expected_answer: str | None = None
    expected_quotes: list[ExpectedQuote] | None = None
    answerable: bool | None = None
    ask_as: str | None = None
    tags: list[str] | None = None
    reason: str = Field(min_length=3)


class PromoteFeedbackRequest(ApiModel):
    answerable: bool
    expected_answer: str | None
    expected_quotes: list[ExpectedQuote]
    ask_as: str | None
    reason: str = Field(min_length=3)


class EvalMetrics(ApiModel):
    n_questions: int
    recall_at_k: float
    mrr: float
    correctness: float
    faithfulness: float
    citation_precision: float
    citation_recall: float
    refusal_accuracy: float
    restricted_refusal_accuracy: float
    answerable_refusal_rate: float


class EvalRunCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    config: PipelineConfig


class EvalRun(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    config: PipelineConfig
    status: EvalRunStatus
    metrics: EvalMetrics | None
    error: str | None
    created_at: datetime


class EvalItem(ApiModel):
    golden_question_id: uuid.UUID
    question: str
    answerable: bool
    answer_status: AnswerStatus
    hit_rank: int | None
    scores: dict[str, float]


class EvalRunDetail(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    config: PipelineConfig
    status: EvalRunStatus
    metrics: EvalMetrics | None
    error: str | None
    created_at: datetime
    items: list[EvalItem]


class EvalCompare(ApiModel):
    base: EvalRun
    head: EvalRun
    deltas: dict[str, float]


class Candidate(ApiModel):
    chunk_id: uuid.UUID
    document_title: str
    rank: int
    score: float
    snippet: str


class RetrievalExplain(ApiModel):
    query: str
    config: PipelineConfig
    allowed_collections: int
    vector: list[Candidate]
    fts: list[Candidate]
    fused: list[Candidate]
    reranked: list[Candidate]


class Health(ApiModel):
    status: Literal["ok", "degraded"]
    database: bool
