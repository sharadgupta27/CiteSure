"""The egress guard decides what may leave the system. Each rule gets a test that would fail if the rule were removed,
and every blocked decision is checked for leaking the text it blocked."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.egress.guard import EgressGuard, normalised_words, word_windows

SECRET_TEXT = "Project Phoenix churn model uses the retention formula 0.37 times weekly active seats"


class FakeCorpus:
    """Stands in for the database: documents are plain strings, phrases match as word sequences."""

    def __init__(self, documents: list[str] | None = None, names: list[str] | None = None) -> None:
        self._documents = [normalised_words(d) for d in documents or []]
        self._names = names or []
        self.phrase_calls = 0

    async def contains_any_phrase(self, phrases: list[list[str]]) -> bool:
        self.phrase_calls += 1
        for phrase in phrases:
            for doc in self._documents:
                if any(doc[i : i + len(phrase)] == phrase for i in range(len(doc) - len(phrase) + 1)):
                    return True
        return False

    async def names(self) -> list[str]:
        return self._names


def guard(corpus: FakeCorpus | None = None, **settings: object) -> EgressGuard:
    return EgressGuard(Settings(env="test", **settings), corpus)  # type: ignore[arg-type]


async def reasons(text: str, g: EgressGuard, kind: str = "query") -> tuple[str, ...]:
    return (await g.check(text, kind=kind)).reasons  # type: ignore[arg-type]


async def test_ordinary_research_query_is_allowed() -> None:
    decision = await guard(FakeCorpus([SECRET_TEXT])).check("transformer attention efficiency", kind="query")
    assert decision.allowed and decision.reasons == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("contact jane.doe@acme.com about attention", "pii:email"),
        ("ssn 123-45-6789 attention", "pii:us_ssn"),
        ("key sk-abcdefghijklmnopqrstuv attention", "secret:api_key"),
        ("AKIAABCDEFGHIJKLMNOP attention", "secret:aws_key"),
        ("-----BEGIN RSA PRIVATE KEY----- attention", "secret:private_key"),
        ("ghp_abcdefghijklmnopqrstuvwxyz attention", "secret:token"),
        ("host 10.1.2.3 attention", "internal_address"),
        ("db.prod.internal attention", "internal_address"),
        ("wiki.corp attention", "internal_address"),
        ("Company Confidential attention", "confidential_marker"),
        ("do not distribute attention", "confidential_marker"),
    ],
)
async def test_static_patterns_block(text: str, expected: str) -> None:
    assert expected in await reasons(text, guard())


async def test_empty_and_too_long_queries_are_blocked() -> None:
    assert await reasons("   ", guard()) == ("empty",)
    assert "too_long" in await reasons("word " * 200, guard(egress_max_query_chars=100))
    # the length cap is for queries; a full question has its own 1000-character limit at the API
    assert "too_long" not in await reasons("word " * 200, guard(egress_max_query_chars=100), kind="question")


async def test_deny_terms_match_whole_words_case_insensitively() -> None:
    g = guard(egress_deny_terms="Phoenix, Acme Corp")
    assert "deny_term" in await reasons("what is phoenix doing", g)
    assert "deny_term" in await reasons("ACME CORP pricing", g)
    assert "deny_term" not in await reasons("phoenixville history", g)  # not the same word


async def test_canaries_block_anywhere_in_the_text() -> None:
    g = guard(egress_canaries="CANARY-7f3a")
    assert "canary" in await reasons("anything canary-7F3A at all", g)


async def test_text_copied_from_a_document_is_blocked() -> None:
    corpus = FakeCorpus([SECRET_TEXT])
    g = guard(corpus)
    assert "copied_from_documents" in await reasons(
        "explain that Project Phoenix churn model uses the retention formula", g, kind="question"
    )


async def test_short_overlap_with_documents_is_allowed() -> None:
    # fewer shared words in a row than egress_overlap_words (6): ordinary vocabulary, not a copied passage
    corpus = FakeCorpus([SECRET_TEXT])
    assert await reasons("churn model retention", guard(corpus)) == ()


async def test_internal_names_block_only_when_enabled() -> None:
    corpus = FakeCorpus(names=["People Ops Confidential", "Handbook"])
    assert "internal_name" in await reasons("summarise people ops confidential", guard(corpus, private_mode=True))
    assert "internal_name" not in await reasons(
        "summarise people ops confidential", guard(corpus)
    )  # off outside private mode
    assert "internal_name" in await reasons(
        "summarise people ops confidential", guard(corpus, egress_block_internal_titles=True)
    )


async def test_allow_terms_exempt_generic_document_titles() -> None:
    corpus = FakeCorpus(names=["Parental Leave Policy"])
    assert "internal_name" in await reasons("parental leave policy research", guard(corpus, private_mode=True))
    allowed = guard(corpus, private_mode=True, egress_allow_terms="parental leave policy")
    assert await reasons("parental leave policy research", allowed) == ()


async def test_a_blocked_decision_never_contains_the_blocked_text() -> None:
    g = guard(FakeCorpus([SECRET_TEXT]), egress_deny_terms="Phoenix", egress_canaries="CANARY-7f3a")
    text = f"{SECRET_TEXT} jane.doe@acme.com sk-abcdefghijklmnopqrstuv CANARY-7f3a"
    decision = await g.check(text, kind="question")
    assert not decision.allowed
    rendered = repr(decision) + decision.summary
    for fragment in ("Phoenix", "jane.doe", "sk-abc", "7f3a", "0.37"):
        assert fragment.lower() not in rendered.lower()


async def test_log_lines_never_contain_the_blocked_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    await guard(egress_deny_terms="Phoenix").check("Phoenix roadmap", kind="query")
    assert "egress blocked" in caplog.text and "Phoenix" not in caplog.text


def test_word_windows_are_bounded() -> None:
    words = [f"w{i}" for i in range(5000)]
    assert len(word_windows(words, 6)) == 400
    assert word_windows(["a", "b"], 6) == []
