"""The structured answer the model must return (mirrors answer_json in plan.md section 4).

Citations name a *source id* ("S1", "S2"...) from the prompt, not a database id: the model never sees or
invents real chunk ids, and an unknown id is simply an unverifiable citation.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DraftCitation(BaseModel):
    source_id: str
    quote: str


class DraftClaim(BaseModel):
    text: str
    citations: list[DraftCitation] = Field(default_factory=list)


class AnswerDraft(BaseModel):
    claims: list[DraftClaim] = Field(default_factory=list)
    refusal: str | None = None


class EntailmentVerdict(BaseModel):
    verdict: Literal["supported", "partial", "unsupported"]
    reason: str = ""


class CorrectnessVerdict(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    reason: str = ""


def _nullable_string() -> dict[str, Any]:
    return {"anyOf": [{"type": "string"}, {"type": "null"}]}


ANSWER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"source_id": {"type": "string"}, "quote": {"type": "string"}},
                            "required": ["source_id", "quote"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["text", "citations"],
                "additionalProperties": False,
            },
        },
        "refusal": _nullable_string(),
    },
    "required": ["claims", "refusal"],
    "additionalProperties": False,
}

ENTAILMENT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["supported", "partial", "unsupported"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}

CORRECTNESS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"score": {"type": "number"}, "reason": {"type": "string"}},
    "required": ["score", "reason"],
    "additionalProperties": False,
}
