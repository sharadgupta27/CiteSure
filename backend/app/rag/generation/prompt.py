"""Builds the prompts. Prompts are versioned files in prompts/; a prompt change is a RAG change (run the evals)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.rag.types import ScoredChunk

PROMPT_DIR = Path(__file__).parent / "prompts"
ANSWER_PROMPT = "answer_v1"
ENTAILMENT_PROMPT = "entailment_v1"
JUDGE_PROMPT = "judge_v1"


@lru_cache
def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class SourceBlock:
    id: str
    document_title: str
    heading: str
    text: str


# Our own delimiters plus tags a document might forge to look like a system, user or tool message.
_FORGEABLE = (
    "source|sources|evidence|claim|question|system|assistant|user|human|developer|instructions?|prompt|tool|"
    "tool_use|tool_result|function|thinking|document|documents|context|answer|response|rules?"
)
_TAG = re.compile(rf"<(/?)\s*({_FORGEABLE})\b", re.IGNORECASE)
_ATTR_UNSAFE = re.compile(r"[<>\"\n\r]")


def neutralise_tags(text: str) -> str:
    """Document text must not be able to close our delimiters (`</source>`) and smuggle in text that looks like
    it came from us. Only the delimiter-like sequences are changed, so quotes still match the original text."""
    return _TAG.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}", text)


def attribute(value: str) -> str:
    return _ATTR_UNSAFE.sub(" ", value)[:200]


def build_sources(chunks: list[ScoredChunk]) -> tuple[list[SourceBlock], dict[str, ScoredChunk]]:
    """Id-tag the chunks (S1, S2, ...). The model cites these ids; the mapping back to real chunks stays server-side."""
    blocks: list[SourceBlock] = []
    id_map: dict[str, ScoredChunk] = {}
    for index, chunk in enumerate(chunks, start=1):
        source_id = f"S{index}"
        blocks.append(SourceBlock(source_id, chunk.document_title, " > ".join(chunk.heading_path), chunk.text))
        id_map[source_id] = chunk
    return blocks, id_map


def render_user_message(question: str, blocks: list[SourceBlock]) -> str:
    rendered = "\n".join(
        f'<source id="{b.id}" document="{attribute(b.document_title)}" section="{attribute(b.heading)}">\n'
        f"{neutralise_tags(b.text)}\n</source>"
        for b in blocks
    )
    return f"<sources>\n{rendered}\n</sources>\n\n<question>\n{neutralise_tags(question)}\n</question>"


def render_entailment_message(claim: str, evidence: str) -> str:
    return f"<evidence>\n{neutralise_tags(evidence)}\n</evidence>\n\n<claim>\n{neutralise_tags(claim)}\n</claim>"
