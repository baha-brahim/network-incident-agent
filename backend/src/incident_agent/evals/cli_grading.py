"""Commands for grading: `grade`, `human-pack` and `agreement`.

    evals grade --run baseline-test [--reasoning on|off] [--max-cases N] [--only ID,ID] [--redo]
    evals human-pack --run baseline-test --n 20
    evals agreement --run baseline-test --human evals/human/baseline-test/human_grades.json

A run lives in `<runs-dir>/<run>/` (default `evals/runs`): `cases/<case_id>.json` are the saved
`CaseArtifact`s. Grades by the grader model are written to `grades/<case_id>.json` (reasoning off)
or `grades-reasoning/<case_id>.json` (reasoning on); a case that already has a grade is skipped, so
a run can be stopped and resumed.
"""

import argparse
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from incident_agent.config import REPO_ROOT, get_settings
from incident_agent.evals import agreement as agreement_mod
from incident_agent.evals import grader, human
from incident_agent.evals.rundir import RUNS_DIR, RunDir, dumps, write_text
from incident_agent.evals.types import CaseArtifact, ReportGrade
from incident_agent.llm.runner import LLMRunner, Runner
from incident_agent.llm.types import AllModelsFailed

DEFAULT_HUMAN_DIR = REPO_ROOT / "evals" / "human"
GROQ_TOKENS_PER_MINUTE = 8000  # free tier; also the cap of one request
DEFAULT_TOKEN_BUDGET = 150_000  # of the provider's 200,000 a day, leaving room for other use
RATE_LIMIT_WAIT_S = 65.0
MAX_RATE_LIMIT_RETRIES = 3
OUTPUT_TOKENS = {False: 1200, True: 2800}  # requested completion budget, by reasoning on/off

_RATE_LIMIT = re.compile(r"(?i)\b429\b|rate.?limit|too many requests|tokens per minute|\bTPM\b")


class QuotaStop(Exception):
    """The run must stop: the daily quota or the token budget is used up."""


# --- files ----------------------------------------------------------------------------------


def open_run(args: argparse.Namespace) -> RunDir:
    return RunDir(args.run, Path(args.runs_dir))


def grades_path(run: RunDir, reasoning: bool) -> Path:
    return run.path / ("grades-reasoning" if reasoning else "grades")


def read_grades(directory: Path) -> list[ReportGrade]:
    if not directory.is_dir():
        return []
    return [
        ReportGrade.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("*.json"))
    ]


# --- grade ----------------------------------------------------------------------------------


def make_runner(reasoning: bool) -> LLMRunner:
    settings = get_settings()
    cache = settings.llm_cache_dir / ("grader-on" if reasoning else "grader-off")
    return LLMRunner(
        "grader",
        cache_mode="readwrite",
        cache_dir=cache,
        reasoning=reasoning,
        max_output_tokens=OUTPUT_TOKENS[reasoning],
    )


class CaseLine(BaseModel):
    case_id: str
    items: int
    score: float | None
    not_verifiable: int
    calls: int
    cached_calls: int
    input_tokens: int
    output_tokens: int
    seconds: float
    resumed: bool = False  # the grade file already existed


def minute_cost(grade: ReportGrade, reasoning: bool) -> float:
    """Seconds of the provider's per-minute token allowance a graded report used.

    The provider counts the requested completion budget as well as the prompt, so that is what
    is charged for every call that actually reached it.
    """
    usage = grade.extra.get("usage", {})
    live_calls = usage.get("calls", 0) - usage.get("cached_calls", 0)
    if live_calls <= 0:
        return 0.0
    requested = usage.get("input_tokens", 0) + live_calls * OUTPUT_TOKENS[reasoning]
    return float(requested / GROQ_TOKENS_PER_MINUTE * 60.0)


def grade_case(
    artifact: CaseArtifact,
    runner_factory: Callable[[], Runner],
    *,
    reasoning: bool,
    sleep: Callable[[float], None] = time.sleep,
) -> ReportGrade:
    """Grade one case, waiting out per-minute limits; raises `QuotaStop` at the daily limit."""
    runner = runner_factory()
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            return grader.grade_report(artifact, runner, reasoning=reasoning)
        except AllModelsFailed as exc:
            if grader.is_daily_limit(exc):
                raise QuotaStop("the provider's daily quota is used up") from exc
            text = " ".join(a.error or "" for a in exc.attempts)
            if _RATE_LIMIT.search(text) and attempt < MAX_RATE_LIMIT_RETRIES:
                print(f"  rate limited; waiting {RATE_LIMIT_WAIT_S:.0f}s", flush=True)
                sleep(RATE_LIMIT_WAIT_S)
                runner = runner_factory()  # a fresh runner has no cooldown
                continue
            raise
    raise AssertionError("unreachable")


def _case_line(grade: ReportGrade, seconds: float, resumed: bool) -> CaseLine:
    f = grader.faithfulness(grade.findings)
    usage = grade.extra.get("usage", {})
    return CaseLine(
        case_id=grade.case_id,
        items=f.n_items,
        score=f.score,
        not_verifiable=f.n_not_verifiable,
        calls=usage.get("calls", 0),
        cached_calls=usage.get("cached_calls", 0),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        seconds=round(seconds, 1),
        resumed=resumed,
    )


def _fmt_score(score: float | None) -> str:
    return "  n/a" if score is None else f"{score:.2f}"


def summarise(lines: list[CaseLine], grades: list[ReportGrade], live_tokens: int) -> dict[str, Any]:
    pooled = grader.faithfulness(f for g in grades for f in g.findings)
    scores = [ln.score for ln in lines if ln.score is not None]
    return {
        "reports": len(lines),
        "mean_report_faithfulness": sum(scores) / len(scores) if scores else None,
        "pooled": pooled.model_dump(),
        "tokens_input": sum(ln.input_tokens for ln in lines),
        "tokens_output": sum(ln.output_tokens for ln in lines),
        "tokens_live_this_run": live_tokens,
        "per_report": [ln.model_dump() for ln in lines],
    }


def cmd_grade(args: argparse.Namespace) -> int:
    reasoning = args.reasoning == "on"
    run = open_run(args)
    out_dir = grades_path(run, reasoning)
    artifacts = run.load_artifacts()
    if not artifacts:
        raise SystemExit(f"No cases found in {run.cases_dir}")
    if args.only:
        wanted = set(args.only.split(","))
        artifacts = [
            a for a in artifacts if a.case.case_id in wanted or a.case.scenario_id in wanted
        ]
    todo = [a for a in artifacts if a.result is not None and a.error is None]
    skipped = len(artifacts) - len(todo)
    if skipped:
        print(f"{skipped} case(s) skipped: no finished report to grade")
    print(
        f"grading {len(todo)} reports from {run.name} "
        f"(reasoning {args.reasoning}, grades in {out_dir})"
    )
    lines: list[CaseLine] = []
    grades: list[ReportGrade] = []
    live_tokens = 0
    graded_now = 0
    ready_at = 0.0  # monotonic time at which the per-minute allowance has recovered
    stop_reason = ""
    for artifact in todo:
        path = out_dir / f"{artifact.case.case_id}.json"
        if path.exists() and not args.redo:
            grade = ReportGrade.model_validate_json(path.read_text(encoding="utf-8"))
            lines.append(_case_line(grade, 0.0, resumed=True))
            grades.append(grade)
            continue
        if args.max_cases is not None and graded_now >= args.max_cases:
            break
        if live_tokens >= args.token_budget:
            stop_reason = f"token budget of {args.token_budget} reached"
            break
        if (pause := ready_at - time.monotonic()) > 0:
            time.sleep(pause)
        started = time.perf_counter()
        try:
            grade = grade_case(
                artifact,
                lambda: make_runner(reasoning),
                reasoning=reasoning,
            )
        except QuotaStop as stop:
            stop_reason = str(stop)
            break
        except AllModelsFailed as exc:
            print(f"{artifact.case.case_id}: grader failed: {str(exc)[:300]}")
            continue
        seconds = time.perf_counter() - started
        write_text(path, dumps(grade.model_dump(mode="json")))
        graded_now += 1
        line = _case_line(grade, seconds, resumed=False)
        lines.append(line)
        grades.append(grade)
        used = grade.extra.get("usage", {}).get("live_tokens", 0)
        live_tokens += used
        print(
            f"{line.case_id}: {line.items} items, faithfulness {_fmt_score(line.score)}, "
            f"{line.not_verifiable} not verifiable, {line.calls} call(s) "
            f"({line.cached_calls} cached), tokens in {line.input_tokens} "
            f"out {line.output_tokens}, {line.seconds}s",
            flush=True,
        )
        ready_at = time.monotonic() + max(0.0, minute_cost(grade, reasoning) - seconds)
    summary = summarise(lines, grades, live_tokens)
    summary["reasoning"] = reasoning
    summary["stopped"] = stop_reason or None
    name = "grading_summary_reasoning.json" if reasoning else "grading_summary.json"
    write_text(run.path / name, dumps(summary))
    mean = summary["mean_report_faithfulness"]
    pooled = summary["pooled"]
    print(
        f"\n{len(lines)} reports graded; mean faithfulness {_fmt_score(mean).strip()}; "
        f"{pooled['n_items']} items: "
        + ", ".join(f"{v} {pooled['counts'][v]}" for v in grader.VERDICTS)
    )
    print(f"live tokens this run: {live_tokens}; summary in {run.path / name}")
    if stop_reason:
        print(f"Stopped: {stop_reason}. Run the same command again to continue.")
        return 2
    return 0


# --- human pack -----------------------------------------------------------------------------


def cmd_human_pack(args: argparse.Namespace) -> int:
    run = open_run(args)
    artifacts = run.load_artifacts()
    chosen = human.select_cases(artifacts, args.n, args.seed)
    if not chosen:
        raise SystemExit("No finished reports to put in the page.")
    pack = human.build_pack(chosen)
    out = Path(args.out) if args.out else DEFAULT_HUMAN_DIR / args.run
    page, items = human.write_pack(pack, out)
    n_items = sum(len(r["items"]) for r in pack["reports"])
    right = sum(human.is_correct(a) for a in chosen)
    kinds = len({a.truth.kind for a in chosen})
    print(
        f"{len(chosen)} reports, {n_items} items, {kinds} scenario kinds "
        f"({right} reports with the right answer, {len(chosen) - right} without)"
    )
    print(f"page: {page}\nitems: {items}")
    print(
        "Open the page in a browser, grade, press Export, and save the file as human_grades.json."
    )
    return 0


# --- agreement ------------------------------------------------------------------------------


def cmd_agreement(args: argparse.Namespace) -> int:
    run = open_run(args)
    people = human.read_human_grades(Path(args.human))
    rater = people[0].grader if people else "human"
    off = read_grades(grades_path(run, False))
    on = read_grades(grades_path(run, True))
    results = []
    if off:
        results.append(agreement_mod.compare_raters(rater, people, "grader (reasoning off)", off))
    if on:
        results.append(agreement_mod.compare_raters(rater, people, "grader (reasoning on)", on))
    if off and on:
        results.append(
            agreement_mod.compare_raters("grader (reasoning off)", off, "grader (reasoning on)", on)
        )
    if not results:
        raise SystemExit(f"No grader grades in {grades_path(run, False)}; run `grade` first.")
    for ag in results:
        print(agreement_mod.format_agreement(ag))
        print()
    write_text(run.path / "agreement.json", dumps([ag.model_dump() for ag in results]))
    print(f"details in {run.path / 'agreement.json'}")
    return 0


# --- registration ---------------------------------------------------------------------------


def add_commands(sub: Any) -> None:
    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--run", required=True, help="run name, e.g. baseline-test")
        p.add_argument("--runs-dir", default=str(RUNS_DIR), help="folder holding the runs")

    g = sub.add_parser("grade", help="grade the faithfulness of a run's reports with the judge")
    common(g)
    g.add_argument("--reasoning", choices=["on", "off"], default="off")
    g.add_argument("--max-cases", type=int, default=None, help="grade at most N new reports")
    g.add_argument("--only", default=None, help="comma-separated case or scenario ids")
    g.add_argument("--redo", action="store_true", help="grade again even if a grade exists")
    g.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    g.set_defaults(func=cmd_grade)

    h = sub.add_parser("human-pack", help="build the page for grading reports by hand")
    common(h)
    h.add_argument("--n", type=int, default=20, help="number of reports")
    h.add_argument("--seed", type=int, default=0, help="sampling seed")
    h.add_argument("--out", default=None, help="output directory (default evals/human/<run>)")
    h.set_defaults(func=cmd_human_pack)

    a = sub.add_parser("agreement", help="compare human grades with the grader's")
    common(a)
    a.add_argument("--human", required=True, help="path of the exported human_grades.json")
    a.set_defaults(func=cmd_agreement)
