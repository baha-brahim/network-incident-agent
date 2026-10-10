"""The grading commands on a small run directory, with a scripted judge."""

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from incident_agent.evals import cli_grading
from incident_agent.evals.rundir import RunDir, dumps, write_text
from incident_agent.evals.types import ReportGrade
from incident_agent.llm.testing import RecordedCall, ScriptedRunner
from incident_agent.llm.types import AllModelsFailed, Attempt
from tests.grading_support import make_artifact, verdict_script


def make_run(root: Path, n: int = 3, name: str = "unit") -> RunDir:
    run = RunDir(name, root)
    for k in range(n):
        run.save_artifact(make_artifact(f"s42-SCN-00{k}-q0"))
    run.save_artifact(make_artifact("s42-SCN-099-q0", error="quota"))
    return run


def parse(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    cli_grading.add_commands(parser.add_subparsers(dest="command", required=True))
    return parser.parse_args(argv)


def grade_args(root: Path, *extra: str) -> argparse.Namespace:
    return parse("grade", "--run", "unit", "--runs-dir", str(root), *extra)


def failing(error: str) -> AllModelsFailed:
    return AllModelsFailed([Attempt(model="groq:m", status="error", error=error)])


@pytest.fixture(autouse=True)
def scripted_judge(monkeypatch: pytest.MonkeyPatch) -> list[ScriptedRunner]:
    runners: list[ScriptedRunner] = []

    def factory(reasoning: bool) -> ScriptedRunner:
        runner = ScriptedRunner(verdict_script("supported"))
        runners.append(runner)
        return runner

    monkeypatch.setattr(cli_grading, "make_runner", factory)
    monkeypatch.setattr(cli_grading.time, "sleep", lambda s: None)
    return runners


def judge_calls(runners: list[ScriptedRunner]) -> int:
    return sum(len(r.calls) for r in runners)


def test_grade_writes_one_file_per_case_and_skips_crashed_cases(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    assert cli_grading.cmd_grade(grade_args(tmp_path)) == 0
    files = sorted(p.name for p in (run.path / "grades").glob("*.json"))
    assert files == ["s42-SCN-000-q0.json", "s42-SCN-001-q0.json", "s42-SCN-002-q0.json"]
    grade = ReportGrade.model_validate_json((run.path / "grades" / files[0]).read_text("utf-8"))
    assert len(grade.findings) == 4
    summary = json.loads((run.path / "grading_summary.json").read_text("utf-8"))
    assert summary["reports"] == 3 and summary["mean_report_faithfulness"] == 1.0
    assert summary["stopped"] is None


def test_grade_resumes_and_does_not_call_the_judge_for_finished_cases(
    tmp_path: Path, scripted_judge: list[ScriptedRunner]
) -> None:
    make_run(tmp_path)
    cli_grading.cmd_grade(grade_args(tmp_path, "--max-cases", "2"))
    assert judge_calls(scripted_judge) == 2
    scripted_judge.clear()
    cli_grading.cmd_grade(grade_args(tmp_path))
    assert judge_calls(scripted_judge) == 1  # only the third case
    scripted_judge.clear()
    cli_grading.cmd_grade(grade_args(tmp_path))
    assert judge_calls(scripted_judge) == 0
    cli_grading.cmd_grade(grade_args(tmp_path, "--redo", "--only", "s42-SCN-001-q0"))
    assert judge_calls(scripted_judge) == 1


def test_reasoning_grades_go_to_their_own_folder(tmp_path: Path) -> None:
    run = make_run(tmp_path, n=1)
    cli_grading.cmd_grade(grade_args(tmp_path, "--reasoning", "on"))
    assert (run.path / "grades-reasoning" / "s42-SCN-000-q0.json").exists()
    assert not (run.path / "grades").exists()
    assert (run.path / "grading_summary_reasoning.json").exists()


def test_a_daily_quota_stops_the_run_cleanly_and_keeps_finished_grades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(tmp_path)
    calls = {"n": 0}

    def factory(reasoning: bool) -> ScriptedRunner:
        def script(call: RecordedCall) -> Any:
            calls["n"] += 1
            if calls["n"] == 2:
                raise failing("429 tokens per day (TPD)")
            return verdict_script("supported")(call)

        return ScriptedRunner(script)

    monkeypatch.setattr(cli_grading, "make_runner", factory)
    assert cli_grading.cmd_grade(grade_args(tmp_path)) == 2
    assert len(list((run.path / "grades").glob("*.json"))) == 1
    out = capsys.readouterr().out
    assert "daily quota is used up" in out and "Run the same command again" in out
    assert json.loads((run.path / "grading_summary.json").read_text("utf-8"))["stopped"]


def test_the_token_budget_stops_the_run(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    assert cli_grading.cmd_grade(grade_args(tmp_path, "--token-budget", "1")) == 2
    assert len(list((run.path / "grades").glob("*.json"))) == 1  # the budget is checked per case


def test_a_per_minute_limit_waits_and_retries_with_a_fresh_runner() -> None:
    sleeps: list[float] = []
    attempts = {"n": 0}

    def factory() -> ScriptedRunner:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return ScriptedRunner([failing("429 tokens per minute")])
        return ScriptedRunner(verdict_script())

    grade = cli_grading.grade_case(make_artifact(), factory, reasoning=False, sleep=sleeps.append)
    assert sleeps == [cli_grading.RATE_LIMIT_WAIT_S] and attempts["n"] == 2
    assert len(grade.findings) == 4


def test_a_persistent_per_minute_limit_gives_up() -> None:
    def always_limited(call: RecordedCall) -> Any:
        raise failing("429 rate limit")

    with pytest.raises(AllModelsFailed):
        cli_grading.grade_case(
            make_artifact(), lambda: ScriptedRunner(always_limited), reasoning=False,
            sleep=lambda s: None,
        )  # fmt: skip


def test_minute_cost_counts_the_requested_completion_budget() -> None:
    usage = {"calls": 2, "cached_calls": 1, "input_tokens": 4000, "output_tokens": 100}
    grade = ReportGrade(case_id="c", grader="g", findings=[], extra={"usage": usage})
    expected = (4000 + cli_grading.OUTPUT_TOKENS[False]) / 8000 * 60
    assert cli_grading.minute_cost(grade, False) == pytest.approx(expected)
    cached = {"calls": 1, "cached_calls": 1, "input_tokens": 4000}
    assert (
        cli_grading.minute_cost(
            ReportGrade(case_id="c", grader="g", findings=[], extra={"usage": cached}), False
        )
        == 0.0
    )


def test_human_pack_then_agreement_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(tmp_path, n=3)
    out = tmp_path / "human"
    pack_args = ("human-pack", "--run", "unit", "--runs-dir", str(tmp_path))
    assert cli_grading.cmd_human_pack(parse(*pack_args, "--n", "2", "--out", str(out))) == 0
    assert (out / "grading.html").exists() and (out / "items.json").exists()
    items = json.loads((out / "items.json").read_text("utf-8"))
    assert len(items["reports"]) == 2

    cli_grading.cmd_grade(grade_args(tmp_path))
    human_grades = [
        {
            "case_id": r["case_id"],
            "grader": "human:Sam",
            "findings": [
                {"index": i["index"], "verdict": "unsupported" if i["index"] == 0 else "supported"}
                for i in r["items"]
            ],
        }
        for r in items["reports"]
    ]
    path = tmp_path / "human_grades.json"
    write_text(path, dumps(human_grades))
    capsys.readouterr()
    agreement_args = ("agreement", "--run", "unit", "--runs-dir", str(tmp_path))
    assert cli_grading.cmd_agreement(parse(*agreement_args, "--human", str(path))) == 0
    text = capsys.readouterr().out
    assert "human:Sam vs grader (reasoning off): 8 items in 2 reports" in text
    result = json.loads((run.path / "agreement.json").read_text("utf-8"))
    assert result[0]["n_items"] == 8
    assert result[0]["kappa_4class"]["status"] == "undefined"  # the judge said "supported" only
