"""Tests for the nightly agent (no network: GitHub is a mock transport)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import agent

GOOD = {
    "recall_at_k": 1.0, "mrr": 0.98, "correctness": 0.8, "faithfulness": 1.0, "citation_precision": 0.91,
    "citation_recall": 0.97, "refusal_accuracy": 0.9, "restricted_refusal_accuracy": 1.0, "answerable_refusal_rate": 0.03,
}


def test_identical_runs_are_not_a_regression() -> None:
    _, regressions = agent.compare(GOOD, GOOD)
    assert regressions == []


def test_small_noise_is_tolerated_but_a_real_drop_is_flagged() -> None:
    _, regressions = agent.compare({**GOOD, "mrr": 0.97}, GOOD)
    assert regressions == []
    _, regressions = agent.compare({**GOOD, "mrr": 0.80, "recall_at_k": 0.85}, GOOD)
    assert {r.metric for r in regressions} == {"mrr", "recall_at_k"}


def test_for_wrongful_refusals_higher_is_worse() -> None:
    _, regressions = agent.compare({**GOOD, "answerable_refusal_rate": 0.20}, GOOD)
    assert [r.metric for r in regressions] == ["answerable_refusal_rate"]
    _, improved = agent.compare({**GOOD, "answerable_refusal_rate": 0.0}, GOOD)
    assert improved == []


def test_answering_a_restricted_question_is_always_critical_even_without_history() -> None:
    _, regressions = agent.compare({**GOOD, "restricted_refusal_accuracy": 0.8}, None)
    assert regressions[0].metric == "restricted_refusal_accuracy"
    report = agent.render_report("hybrid+rerank", *agent.compare({**GOOD, "restricted_refusal_accuracy": 0.8}, None), [])
    assert "CRITICAL" in report and "test_acl_leaks" in report


def test_the_report_lists_every_metric_and_the_suspects() -> None:
    changes, regressions = agent.compare({**GOOD, "recall_at_k": 0.7}, GOOD)
    report = agent.render_report("hybrid+rerank", changes, regressions, ["- “Q?”: ranking"])
    assert report.count("|") > 30 and "recall_at_k" in report and "chunking" in report
    assert "retrieval-debugger" in report and "Do not edit the golden set" in report


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"answerable": True, "answer_status": "refused", "hit_rank": None}, "retrieval or chunking"),
        ({"answerable": True, "answer_status": "refused", "hit_rank": 5}, "ranking"),
        ({"answerable": True, "answer_status": "refused", "hit_rank": 1}, "generation or verification"),
        ({"answerable": False, "answer_status": "answered", "hit_rank": None}, "access control or refusal policy"),
    ],
)
def test_questions_are_classified_by_stage(item: dict, expected: str) -> None:
    assert expected in agent.classify_question(item)


def github(handler) -> httpx.MockTransport:  # type: ignore[no-untyped-def]
    return httpx.MockTransport(handler)


def test_opens_one_issue_then_comments_instead_of_duplicating() -> None:
    created: list[dict] = []

    def first(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        created.append(json.loads(request.content))
        return httpx.Response(201, json={"number": 7})

    assert agent.github_issue("report", "hybrid+rerank", "o/r", "tok", github(first)) == "opened #7"
    assert created[0]["labels"] == ["rag-regression"] and created[0]["title"] == "Nightly RAG regression: hybrid+rerank"

    posted: list[str] = []

    def second(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[{"number": 7, "title": "Nightly RAG regression: hybrid+rerank"}])
        posted.append(request.url.path)
        return httpx.Response(201, json={})

    assert agent.github_issue("report", "hybrid+rerank", "o/r", "tok", github(second)) == "commented on #7"
    assert posted == ["/repos/o/r/issues/7/comments"]


def test_the_token_is_sent_only_to_github_in_the_authorization_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[]) if request.method == "GET" else httpx.Response(201, json={"number": 1})

    agent.github_issue("body", "x", "o/r", "ghp_secret", github(handler))
    assert all(r.headers["authorization"] == "Bearer ghp_secret" and r.url.host == "api.github.com" for r in seen)
    assert all("ghp_secret" not in r.content.decode() for r in seen)


def write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_cli_exit_codes_and_previous_file_handling(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    results = write(tmp_path / "now.json", {"hybrid+rerank": GOOD})
    previous = tmp_path / "last.json"
    assert agent.main(["--results", str(results), "--previous", str(previous), "--update-previous"]) == 0
    assert json.loads(previous.read_text())["hybrid+rerank"] == GOOD  # first night: baseline stored

    worse = write(tmp_path / "worse.json", {"hybrid+rerank": {**GOOD, "mrr": 0.5}})
    assert agent.main(["--results", str(worse), "--previous", str(previous), "--dry-run"]) == 0
    assert "Nightly RAG evaluation regressed" in capsys.readouterr().out
    assert agent.main(["--results", str(worse), "--previous", str(previous), "--dry-run", "--fail-on-regression"]) == 1


def test_cli_refuses_to_open_an_issue_without_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    previous = write(tmp_path / "prev.json", {"hybrid+rerank": GOOD})
    worse = write(tmp_path / "w.json", {"hybrid+rerank": {**GOOD, "mrr": 0.5}})
    assert agent.main(["--results", str(worse), "--previous", str(previous), "--open-issue"]) == 2
