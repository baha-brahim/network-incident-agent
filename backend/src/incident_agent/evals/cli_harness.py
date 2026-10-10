"""Commands of the harness: prepare, cases, run, score, report."""

import argparse
import sys
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import create_engine

from incident_agent.config import REPO_ROOT, get_settings
from incident_agent.evals.cases import (
    load_planned_cases,
    parse_only,
    select_cases,
    stratified,
)
from incident_agent.evals.prepare import prepare_database, resolve_targets
from incident_agent.evals.rundir import RUNS_DIR, RunDir
from incident_agent.evals.runner import VARIANTS, RunOptions, execute_run
from incident_agent.evals.summary import (
    case_line,
    load_scored_run,
    summary_json,
    summary_lines,
)

RESULTS_DIR = REPO_ROOT / "docs" / "results"
EXIT_QUOTA = 2


def _runs_dir(args: argparse.Namespace) -> Path:
    return Path(args.runs_dir) if args.runs_dir else RUNS_DIR


def cmd_prepare(args: argparse.Namespace) -> int:
    targets = resolve_targets(args.seed, database=args.database)
    report = prepare_database(targets, args.seed, force=args.force)
    print(f"database {report.database}: " + ("created" if report.created else "already existed"))
    print("rows: " + ", ".join(f"{t} {n:,}" for t, n in report.rows.items()))
    print(
        f"alerts {report.alerts}, anomalies {report.anomalies}, "
        f"runbooks {report.runbook_docs} documents / {report.runbook_chunks} chunks"
    )
    print(f"total {sum(report.seconds.values()):.1f}s")
    return 0


def cmd_cases(args: argparse.Namespace) -> int:
    targets = resolve_targets(args.seed, database=args.database)
    engine = create_engine(targets.owner_url)
    try:
        cases = stratified(load_planned_cases(engine, args.seed, args.questions))
    finally:
        engine.dispose()
    run = RunDir(args.run, _runs_dir(args)) if args.run else None
    for n, c in enumerate(cases, 1):
        state = run.case_state(c.case_id) if run else ""
        print(f"{n:>3} {c.case_id:<20} {c.truth.kind:<20} {c.truth.difficulty:<7} {state}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    mode: Literal["readwrite", "replay"] = args.cache_mode or (
        "replay" if settings.llm_cache_mode == "replay" else "readwrite"
    )
    opts = RunOptions(
        name=args.name,
        seed=args.seed,
        variant=args.variant,
        questions=args.questions,
        only=parse_only(args.only),
        max_cases=args.max_cases,
        retry_errors=args.retry_errors,
        cache_mode=mode,
        model=args.model,
        database=args.database,
        runs_dir=_runs_dir(args),
    )
    if opts.only:
        # Fail on a typo before anything runs.
        targets = resolve_targets(args.seed, database=args.database)
        engine = create_engine(targets.owner_url)
        try:
            select_cases(load_planned_cases(engine, args.seed, args.questions), opts.only)
        finally:
            engine.dispose()
    result = execute_run(opts)
    print(
        f"done: {len(result.executed)} run ({len(result.errors)} with an infrastructure error), "
        f"{len(result.skipped_done)} already done, {len(result.skipped_errors)} skipped after "
        f"an earlier error, {result.not_run} left"
    )
    if result.skipped_errors:
        print("  earlier errors are left alone; add --retry-errors to run them again")
    if result.stopped:
        print(f"STOPPED: {result.stopped}")
        print("The model provider has no quota left. Run the same command again later: finished")
        print("cases are skipped and the case that was in flight starts again.")
        return EXIT_QUOTA
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    run = RunDir(args.run, _runs_dir(args))
    scored = load_scored_run(run)
    print("\n".join(summary_lines(scored)))
    print()
    for s in scored.scores:
        print(case_line(s))
    if not args.no_write:
        run.write_summary(summary_json(scored))
        print(f"\nwrote {run.summary_path}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from incident_agent.evals.report import write_report

    out = Path(args.out) if args.out else RESULTS_DIR
    runs = [RunDir(name, _runs_dir(args)) for name in args.runs]
    written = write_report(runs, out)
    for path in written:
        print(f"wrote {path}")
    return 0


def add_commands(sub: Any) -> None:
    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--runs-dir", help=f"default: {RUNS_DIR}")

    p = sub.add_parser("prepare", help="create and fill the evaluation database of a seed")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--database", help="default: the dev database for seed 42, else a per-seed one")
    p.add_argument("--force", action="store_true", help="rebuild the world even if it is loaded")
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("cases", help="list the cases of a seed in run order")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--database")
    p.add_argument("--questions", choices=["first", "all"], default="first")
    p.add_argument("--run", help="show the state of each case in this run")
    common(p)
    p.set_defaults(func=cmd_cases)

    p = sub.add_parser("run", help="run (or resume) the agent on the cases of a seed")
    p.add_argument("--name", required=True, help="run name, e.g. baseline-dev")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--variant", choices=sorted(VARIANTS), default="default")
    p.add_argument("--questions", choices=["first", "all"], default="first")
    p.add_argument("--only", help="comma-separated scenario ids or case ids")
    p.add_argument("--max-cases", type=int, help="run at most this many cases now")
    p.add_argument("--retry-errors", action="store_true", help="also run cases that errored before")
    p.add_argument(
        "--cache-mode",
        choices=["readwrite", "replay"],
        help="default: readwrite, or replay when LLM_CACHE_MODE=replay",
    )
    p.add_argument("--model", help="provider:model; default is the configured agent model")
    p.add_argument("--database")
    common(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("score", help="score a run and write its summary.json")
    p.add_argument("--run", required=True)
    p.add_argument("--no-write", action="store_true")
    common(p)
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("report", help="write docs/results/evaluation.md, .json and charts")
    p.add_argument("--runs", nargs="+", required=True, metavar="RUN")
    p.add_argument("--out", help=f"output directory, default {RESULTS_DIR}")
    common(p)
    p.set_defaults(func=cmd_report)


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point for the harness commands alone."""
    parser = argparse.ArgumentParser(prog="python -m incident_agent.evals.cli_harness")
    sub = parser.add_subparsers(dest="command", required=True)
    add_commands(sub)
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
