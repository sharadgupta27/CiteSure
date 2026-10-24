"""The mapping from a golden-set run to EvalOps' results, and the script that sends them."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.evals.evalops import case_output, case_passed, case_ref, case_score, golden_to_dataset_rows, to_ingest_results

SCRIPT = Path(__file__).resolve().parents[2] / "evals" / "publish_to_evalops.py"
GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "golden.jsonl"


def item(
    *,
    answerable: bool = True,
    status: str = "answered",
    hit_rank: int | None = 1,
    correctness: float = 1.0,
    question: str = "How many weeks?",
) -> Any:
    claims = [SimpleNamespace(text="16 weeks."), SimpleNamespace(text="Fully paid.")] if status == "answered" else []
    return SimpleNamespace(
        golden=SimpleNamespace(answerable=answerable, question=question),
        outcome=SimpleNamespace(status=status, claims=claims, timings={"retrieve": 12.0, "answer": 30.5}),
        hit_rank=hit_rank,
        scores={"correctness": correctness},
    )


def test_case_ref_is_stable_and_ignores_case_and_whitespace() -> None:
    assert case_ref("How many weeks?") == case_ref("  how   MANY weeks? ")
    assert case_ref("How many weeks?") != case_ref("How many days?")
    assert case_ref("x").startswith("q-") and len(case_ref("x")) == 14


@pytest.mark.parametrize(
    ("kwargs", "passed"),
    [
        ({}, True),
        ({"correctness": 0.5}, True),  # half credit is still an answer a user could act on
        ({"correctness": 0.0}, False),
        ({"hit_rank": None}, False),  # right answer by luck: the expected source was never retrieved
        ({"status": "refused"}, False),  # a wrong refusal
        ({"answerable": False, "status": "refused"}, True),
        ({"answerable": False, "status": "answered"}, False),  # answering what it must not answer
    ],
)
def test_case_passed(kwargs: dict[str, Any], passed: bool) -> None:
    assert case_passed(item(**kwargs)) is passed


def test_scores_and_output() -> None:
    assert case_score(item(correctness=0.5)) == 0.5
    assert case_score(item(status="refused")) == 0.0
    assert case_score(item(answerable=False, status="refused")) == 1.0
    assert case_score(item(answerable=False, status="answered")) == 0.0
    assert case_output(item()) == "16 weeks. Fully paid."
    assert case_output(item(status="refused")) == "[refused]"


def test_ingest_results_shape_matches_the_evalops_contract() -> None:
    [row] = to_ingest_results([item()])
    assert set(row) == {"case_ref", "output", "passed", "score", "latency_ms"}
    assert row == {
        "case_ref": case_ref("How many weeks?"),
        "output": "16 weeks. Fully paid.",
        "passed": True,
        "score": 1.0,
        "latency_ms": 42.5,
    }


def test_output_is_cut_to_the_size_evalops_accepts() -> None:
    long = item()
    long.outcome.claims = [SimpleNamespace(text="x" * 9000)]
    assert len(to_ingest_results([long])[0]["output"]) == 5000


def test_dataset_rows_cover_every_golden_question_with_unique_refs() -> None:
    lines = GOLDEN.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(r) for r in golden_to_dataset_rows(lines)]
    assert len(rows) == len([line for line in lines if line.strip()])
    refs = [r["inputs"]["case_ref"] for r in rows]
    assert len(set(refs)) == len(refs)
    assert all(r["inputs"]["question"] and r["expected_output"] for r in rows)
    refused = [r for r in rows if r["expected_output"] == "[refused]"]
    assert refused and all({"out-of-scope", "restricted"} & set(r["tags"]) for r in refused)


def test_export_dataset_cli_writes_the_import_file(tmp_path: Path) -> None:
    # Run it the way the docs say (`python -m`), not by calling main(): a missing __main__ guard went unnoticed once.
    out = tmp_path / "dataset.jsonl"
    done = subprocess.run(  # noqa: S603  (fixed argument list, no external input)
        [sys.executable, "-m", "app.evals.evalops", "--export-dataset", str(out)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert len(out.read_text(encoding="utf-8").splitlines()) == len(GOLDEN.read_text(encoding="utf-8").splitlines())


# --- the publish script against a stand-in EvalOps -----------------------------------------------------------------


def load_script() -> Any:
    spec = importlib.util.spec_from_file_location("publish_to_evalops", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeEvalOps:
    """Answers POST /api/v1/gate/ingest with a scripted sequence of (status, body)."""

    def __init__(self, replies: list[tuple[int, dict[str, Any]]]) -> None:
        self.replies = replies
        self.requests: list[dict[str, Any]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                owner.requests.append(
                    {"path": self.path, "key": self.headers["X-API-Key"], "body": json.loads(self.rfile.read(length))}
                )
                status, payload = owner.replies[min(len(owner.requests), len(owner.replies)) - 1]
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def gate(verdict: str) -> dict[str, Any]:
    return {
        "run_id": 7,
        "baseline_run_id": 3,
        "verdict": verdict,
        "reasons": ["pass rate 92% >= minimum 80%", "0 regressed case(s) <= allowed 0"],
        "pass_rate": 0.92,
        "regressions": 0,
        "cost_increase_pct": None,
        "policy": {"min_pass_rate": 0.8, "max_regressions": 0, "max_cost_increase_pct": 20},
    }


@pytest.fixture
def cases_file(tmp_path: Path) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(to_ingest_results([item()])), encoding="utf-8")
    return path


def run_script(monkeypatch: pytest.MonkeyPatch, args: list[str], **env: str) -> int:
    script = load_script()
    monkeypatch.setattr("sys.argv", ["publish", *args])
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setenv("EVALOPS_API_KEY", env.get("key", "eo_secret"))
    return int(script.main())


def test_publish_sends_the_results_and_exits_on_the_verdict(
    cases_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = FakeEvalOps([(201, gate("pass"))])
    try:
        code = run_script(
            monkeypatch,
            [
                str(cases_file),
                "--url",
                server.url,
                "--dataset-id",
                "5",
                "--head-label",
                "pr-9",
                "--baseline-label",
                "main",
                "--git-sha",
                "abc",
            ],
        )
    finally:
        server.close()
    assert code == 0
    [req] = server.requests
    assert req["path"] == "/api/v1/gate/ingest" and req["key"] == "eo_secret"
    assert req["body"]["dataset_id"] == 5 and req["body"]["baseline_label"] == "main"
    assert req["body"]["head_label"] == "pr-9" and req["body"]["git_sha"] == "abc"
    assert req["body"]["results"][0]["case_ref"] == case_ref("How many weeks?")
    out = capsys.readouterr().out
    assert "PASS" in out and "pass rate 92%" in out and "compare?base=3&head=7" in out
    assert "eo_secret" not in out


def test_publish_fails_the_build_on_a_failing_verdict(cases_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeEvalOps([(201, gate("fail"))])
    try:
        code = run_script(monkeypatch, [str(cases_file), "--url", server.url, "--dataset-id", "5", "--head-label", "pr-9"])
    finally:
        server.close()
    assert code == 1


def test_publish_reports_an_infrastructure_error_as_2_not_as_a_quality_failure(
    cases_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = FakeEvalOps([(422, {"detail": "results must cover the dataset exactly; missing case_ref: q-1"})])
    try:
        code = run_script(monkeypatch, [str(cases_file), "--url", server.url, "--dataset-id", "5", "--head-label", "pr-9"])
    finally:
        server.close()
    assert code == 2
    assert "missing case_ref: q-1" in capsys.readouterr().err
    assert len(server.requests) == 1  # a 4xx is not retried


def test_publish_retries_a_restarting_server(cases_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _s: None)
    server = FakeEvalOps([(503, {"detail": "starting"}), (201, gate("pass"))])
    try:
        code = run_script(monkeypatch, [str(cases_file), "--url", server.url, "--dataset-id", "5", "--head-label", "main"])
    finally:
        server.close()
    assert code == 0 and len(server.requests) == 2


def test_bootstrap_ok_records_the_first_main_run_without_a_baseline(
    cases_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = {"detail": "baseline version 'main' not found"}
    server = FakeEvalOps([(404, missing), (201, gate("pass"))])
    try:
        code = run_script(
            monkeypatch,
            [
                str(cases_file),
                "--url",
                server.url,
                "--dataset-id",
                "5",
                "--head-label",
                "main",
                "--baseline-label",
                "main",
                "--bootstrap-ok",
            ],
        )
    finally:
        server.close()
    assert code == 0
    assert server.requests[0]["body"]["baseline_label"] == "main"
    assert "baseline_label" not in server.requests[1]["body"]


def test_without_bootstrap_ok_an_unknown_baseline_label_is_an_error(
    cases_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = FakeEvalOps([(404, {"detail": "baseline version 'main' not found"})])
    try:
        code = run_script(
            monkeypatch,
            [str(cases_file), "--url", server.url, "--dataset-id", "5", "--head-label", "pr-1", "--baseline-label", "main"],
        )
    finally:
        server.close()
    assert code == 2 and len(server.requests) == 1


def test_bootstrap_ok_does_not_swallow_other_404s(cases_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeEvalOps([(404, {"detail": "dataset not found"})])
    try:
        code = run_script(
            monkeypatch,
            [
                str(cases_file),
                "--url",
                server.url,
                "--dataset-id",
                "5",
                "--head-label",
                "main",
                "--baseline-label",
                "main",
                "--bootstrap-ok",
            ],
        )
    finally:
        server.close()
    assert code == 2 and len(server.requests) == 1


def test_publish_requires_a_key_and_an_http_url(cases_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_script()
    monkeypatch.delenv("EVALOPS_API_KEY", raising=False)
    monkeypatch.delenv("EVALOPS_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["publish", str(cases_file), "--dataset-id", "5", "--head-label", "x"])
    assert script.main() == 2
    monkeypatch.setenv("EVALOPS_API_KEY", "k")
    monkeypatch.setattr(
        "sys.argv", ["publish", str(cases_file), "--url", "file:///etc/passwd", "--dataset-id", "5", "--head-label", "x"]
    )
    assert script.main() == 2


# --- redaction: what EvalOps stores when the corpus is real company data ---------------------------------------------
def test_redacted_results_carry_the_verdict_but_no_answer_text() -> None:
    [row] = to_ingest_results([item(question="What is the Phoenix churn formula?")], redact=True)
    assert row["output"] == "[answered]"
    assert row["passed"] is True and row["score"] == 1.0 and row["latency_ms"] == 42.5
    assert "16 weeks" not in json.dumps(row)
    # a refusal says nothing about content, so it is reported as it is
    assert to_ingest_results([item(status="refused")], redact=True)[0]["output"] == "[refused]"


def test_redacted_dataset_rows_hide_questions_and_reference_answers_but_keep_the_key_and_tags() -> None:
    lines = GOLDEN.read_text(encoding="utf-8").splitlines()
    plain = [json.loads(r) for r in golden_to_dataset_rows(lines)]
    hidden = [json.loads(r) for r in golden_to_dataset_rows(lines, redact=True)]
    assert [r["inputs"]["case_ref"] for r in hidden] == [
        r["inputs"]["case_ref"] for r in plain
    ]  # same keys: results still match
    assert [r["tags"] for r in hidden] == [r["tags"] for r in plain]
    assert {r["inputs"]["question"] for r in hidden} == {"[redacted]"}
    assert {r["expected_output"] for r in hidden} <= {"[redacted]", "[refused]"}
    questions = {json.loads(line)["question"] for line in lines if line.strip()}
    assert not questions & {r["inputs"]["question"] for r in hidden}


def test_private_mode_redacts_the_dataset_export_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.evals.evalops import main

    monkeypatch.setenv("PRIVATE_MODE", "true")
    get_settings.cache_clear()
    out = tmp_path / "dataset.jsonl"
    monkeypatch.setattr("sys.argv", ["evalops", "--export-dataset", str(out)])
    try:
        assert main() == 0
    finally:
        get_settings.cache_clear()
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows and {r["inputs"]["question"] for r in rows} == {"[redacted]"}
