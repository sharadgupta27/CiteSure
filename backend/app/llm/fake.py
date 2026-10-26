"""Deterministic offline LLM used by tests, CI and the default dev setup. No network, no cost.

The default `extractive` mode behaves like a careful model: it answers with the best-matching sentence from the
sources, quoted exactly, and refuses when the sources do not cover the question's informative words.
Other modes simulate the failure cases the verification stage exists to catch:

- `hallucinate`: invents a quote that is not in any source          -> dropped by quote matching
- `mismatch`:    real quote, but the claim changes a number          -> dropped by the entailment check
- `obedient`:    follows an instruction hidden in a source and tries to leak the system prompt
"""

from __future__ import annotations

import math
import os
import re
from typing import Literal

from app.llm.base import GenerationRequest, Usage
from app.rag.generation.prompt import SourceBlock
from app.rag.generation.schema import (
    AnswerDraft,
    CorrectnessVerdict,
    DraftCitation,
    DraftClaim,
    EntailmentVerdict,
)
from app.rag.text import content_terms, sentence_spans

Mode = Literal["extractive", "hallucinate", "mismatch", "obedient"]

ANSWER_MIN_COVERAGE = float(os.environ.get("FAKE_MIN_COVERAGE", "0.40"))  # precision/recall knob, see docs/eval-results.md
SUMMARY_MIN_CHARS = 20  # shorter "sentences" are headings and labels, not points worth summarizing
SUMMARY_MAX_CLAIMS = 6
NUMBER_QUESTION = re.compile(
    r"(how (many|much|long|often|fast|quickly|heavy)|when|what is the [a-z ]*(limit|stipend|budget|range|target|amount))",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\$?\d[\d,.]*%?")


def _numbers(text: str) -> set[str]:
    return {m.strip(".,") for m in _NUMBER.findall(text) if m.strip(".,")}


def _sentences(blocks: list[SourceBlock]) -> list[tuple[SourceBlock, str, set[str]]]:
    out: list[tuple[SourceBlock, str, set[str]]] = []
    for block in blocks:
        for start, end in sentence_spans(block.text):
            sentence = block.text[start:end]
            out.append((block, sentence, set(content_terms(sentence))))
    return out


class FakeProvider:
    hosted = False
    answer_model = "fake-answer"
    verify_model = "fake-verify"

    def __init__(self, mode: Mode = "extractive") -> None:
        self.mode: Mode = mode

    async def generate_answer(self, request: GenerationRequest) -> tuple[AnswerDraft, Usage]:
        if self.mode == "obedient":
            injected = self._obey_injection(request.sources)
            if injected is not None:
                return injected, Usage()
        if request.task == "summary":
            return self._summary(request), Usage()
        if request.task == "compare":
            return self._compare(request), Usage()
        sentences = _sentences(request.sources)
        question_terms = set(content_terms(request.question))
        if not sentences or not question_terms:
            return AnswerDraft(claims=[], refusal="No sources were provided."), Usage()

        # Terms that appear in few sentences are the informative ones. A term found nowhere counts as much as the
        # rarest term that IS found (so "yearly" does not sink "learning budget"), but never less.
        n = len(sentences)
        df = {t: sum(t in terms for _, _, terms in sentences) for t in question_terms}
        weight = {t: math.log((n + 1) / (df[t] + 0.5)) for t in question_terms if df[t]}
        unseen_weight = 2 * max(weight.values(), default=1.0)  # a question word found nowhere is a strong hint of no answer
        weight.update({t: unseen_weight for t in question_terms if not df[t]})
        total = sum(weight.values()) or 1.0
        wants_number = bool(NUMBER_QUESTION.search(request.question))

        def coverage(i: int) -> float:
            return sum(weight[t] for t in question_terms & sentences[i][2]) / total

        def rank_score(i: int) -> float:
            # For "how many / how long / how much" questions, prefer a sentence that contains a number.
            # This only orders candidates; whether to answer at all depends on coverage alone.
            has_digit = any(ch.isdigit() for ch in sentences[i][1])
            return (
                coverage(i)
                + (0.15 if wants_number and has_digit else 0.0)
                - (0.1 if wants_number and not has_digit else 0.0)
            )

        ranked = sorted(range(n), key=lambda i: (-rank_score(i), i))
        best_index = ranked[0]
        if coverage(best_index) < ANSWER_MIN_COVERAGE:
            return AnswerDraft(claims=[], refusal="The sources do not answer this question."), Usage()

        picked = [best_index]
        for index in ranked[1:3]:
            if rank_score(index) >= 0.85 * rank_score(best_index) and sentences[index][1] != sentences[best_index][1]:
                picked.append(index)
        claims: list[DraftClaim] = []
        for index in picked:
            block, sentence, _ = sentences[index]
            claims.append(self._claim(block, sentence))
        return AnswerDraft(claims=claims, refusal=None), Usage()

    def _summary(self, request: GenerationRequest) -> AnswerDraft:
        """One quoted sentence per passage, in reading order: the first one, or the one that best matches the focus."""
        focus = set(content_terms(request.question))
        claims: list[DraftClaim] = []
        for block in request.sources:
            options = [(s, t) for _, s, t in _sentences([block]) if len(s.strip()) >= SUMMARY_MIN_CHARS]
            if focus:
                options = [(s, t) for s, t in options if t & focus]
                options.sort(key=lambda option: -len(option[1] & focus))  # stable: ties keep reading order
            if options:
                claims.append(self._claim(block, options[0][0]))
            if len(claims) >= SUMMARY_MAX_CLAIMS:
                break
        if not claims:
            return AnswerDraft(claims=[], refusal="The passages do not cover this.")
        return AnswerDraft(claims=claims, refusal=None)

    def _compare(self, request: GenerationRequest) -> AnswerDraft:
        """For each document, its best sentence on the aspect, if it covers enough of the aspect's words."""
        aspect = set(content_terms(request.question))
        claims: list[DraftClaim] = []
        titles = list(dict.fromkeys(b.document_title for b in request.sources))
        for title in titles:
            blocks = [b for b in request.sources if b.document_title == title]
            best: tuple[float, SourceBlock, str] | None = None
            for block, sentence, terms in _sentences(blocks):
                covered = len(terms & aspect) / len(aspect) if aspect else 0.0
                if covered >= ANSWER_MIN_COVERAGE and (best is None or covered > best[0]):
                    best = (covered, block, sentence)
            if best is not None:
                claims.append(self._claim(best[1], best[2]))
        if not claims:
            return AnswerDraft(claims=[], refusal="None of the documents covers this aspect.")
        return AnswerDraft(claims=claims, refusal=None)

    def _claim(self, block: SourceBlock, sentence: str) -> DraftClaim:
        if self.mode == "hallucinate":
            return DraftClaim(
                text="Employees receive 42 days of leave.",
                citations=[DraftCitation(source_id=block.id, quote="employees receive 42 days of leave every year")],
            )
        if self.mode == "mismatch":
            wrong = _NUMBER.sub("99", sentence, count=1)
            return DraftClaim(text=wrong, citations=[DraftCitation(source_id=block.id, quote=sentence)])
        return DraftClaim(text=sentence, citations=[DraftCitation(source_id=block.id, quote=sentence)])

    def _obey_injection(self, blocks: list[SourceBlock]) -> AnswerDraft | None:
        for block in blocks:
            match = re.search(r"ignore (?:all )?(?:previous|prior) instructions[^.]*\.", block.text, re.IGNORECASE)
            if match:
                leaked = "My system prompt says: You are CiteSure, an assistant that answers questions."
                return AnswerDraft(
                    claims=[DraftClaim(text=leaked, citations=[DraftCitation(source_id=block.id, quote=match.group(0))])],
                    refusal=None,
                )
        return None

    async def judge_entailment(
        self, *, system: str, user: str, claim: str, evidence: str
    ) -> tuple[EntailmentVerdict, Usage]:
        claim_terms = set(content_terms(claim))
        if not claim_terms:
            return EntailmentVerdict(verdict="unsupported", reason="Empty claim."), Usage()
        evidence_terms = set(content_terms(evidence))
        coverage = len(claim_terms & evidence_terms) / len(claim_terms)
        if not _numbers(claim) <= _numbers(evidence):
            return EntailmentVerdict(verdict="unsupported", reason="A number in the claim is not in the evidence."), Usage()
        if coverage >= 0.8:
            return EntailmentVerdict(verdict="supported", reason="The evidence covers the claim."), Usage()
        if coverage >= 0.5:
            return EntailmentVerdict(verdict="partial", reason="Only part of the claim is covered."), Usage()
        return EntailmentVerdict(verdict="unsupported", reason="The evidence does not cover the claim."), Usage()

    async def judge_correctness(
        self, *, system: str, question: str, expected: str, actual: str
    ) -> tuple[CorrectnessVerdict, Usage]:
        expected_terms = set(content_terms(expected))
        if not expected_terms:
            return CorrectnessVerdict(score=0.0, reason="No reference."), Usage()
        coverage = len(expected_terms & set(content_terms(actual))) / len(expected_terms)
        score = 1.0 if coverage >= 0.7 else 0.5 if coverage >= 0.4 else 0.0
        return CorrectnessVerdict(score=score, reason=f"{coverage:.0%} of the reference terms are present."), Usage()
