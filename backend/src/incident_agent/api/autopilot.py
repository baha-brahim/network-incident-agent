"""Investigate detector alerts from the command line. Each call does bounded work and ends.

    python -m incident_agent.api.autopilot pending [--limit 10] [--min-severity medium]
    python -m incident_agent.api.autopilot run ALR-0019 [--dry-run]
    python -m incident_agent.api.autopilot sweep [--limit 3] [--min-severity medium] [--dry-run]

`pending` and `--dry-run` never call a model. The other commands write runs to the database named
in `.env`, the same runs the webhook creates; a scheduler can invoke `sweep` periodically.
"""

import argparse
import sys

from incident_agent.agent.tools.timeutil import as_utc, fmt
from incident_agent.api.alert_runs import (
    SEVERITIES,
    AlertLimitReached,
    AlertQuestion,
    UnknownAlert,
    alert_question,
    pending_alerts,
    run_alert,
)
from incident_agent.api.schemas import AlertRunOut
from incident_agent.api.services import Services
from incident_agent.config import get_settings


def describe(question: AlertQuestion) -> str:
    return f"asked at {fmt(question.asked_at)}: {question.question}"


def describe_run(outcome: AlertRunOut) -> str:
    run = outcome.run
    state = "started" if outcome.created else "already investigated"
    return (
        f"{run.run_id} ({state}) status={run.status} verdict={run.verdict} cause={run.cause} "
        f"node={run.node_id} confidence={run.confidence}"
    )


def cmd_pending(svc: Services, args: argparse.Namespace) -> int:
    pending = pending_alerts(svc, args.limit, args.min_severity)
    for item in pending:
        print(f"{item.alert_id} [{item.severity}] {describe(item.question)}")
    if not pending:
        print("no pending alerts")
    return 0


def cmd_run(svc: Services, args: argparse.Namespace) -> int:
    if args.dry_run:
        question = alert_question(svc.agent_engine(), args.alert_id, as_utc(svc.facts().now))
        if question is None:
            print(f"unknown alert {args.alert_id}")
            return 1
        print(f"{args.alert_id} {describe(question)}")
        return 0
    try:
        outcome = run_alert(svc, args.alert_id)
    except UnknownAlert:
        print(f"unknown alert {args.alert_id}")
        return 1
    except AlertLimitReached as exc:
        print(f"{exc}; try again after 00:00 UTC")
        return 1
    print(describe_run(outcome))
    return 0 if outcome.run.status == "finished" else 1


def cmd_sweep(svc: Services, args: argparse.Namespace) -> int:
    pending = pending_alerts(svc, args.limit, args.min_severity)
    if not pending:
        print("no pending alerts")
    failed = 0
    for item in pending:
        if args.dry_run:
            print(f"{item.alert_id} [{item.severity}] {describe(item.question)}")
            continue
        try:
            outcome = run_alert(svc, item.alert_id)
        except AlertLimitReached as exc:
            print(f"{item.alert_id}: {exc}; stopping")
            break
        print(f"{item.alert_id} {describe_run(outcome)}")
        failed += outcome.run.status != "finished"
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m incident_agent.api.autopilot", description=__doc__
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def severity(p: argparse.ArgumentParser) -> None:
        p.add_argument("--min-severity", choices=SEVERITIES, default="medium")

    pending = sub.add_parser("pending", help="list alerts that have no investigation yet")
    pending.add_argument("--limit", type=int, default=10)
    severity(pending)
    pending.set_defaults(func=cmd_pending)

    run = sub.add_parser("run", help="investigate one alert")
    run.add_argument("alert_id", metavar="ALERT_ID")
    run.add_argument("--dry-run", action="store_true", help="print the question and stop")
    run.set_defaults(func=cmd_run)

    sweep = sub.add_parser("sweep", help="investigate the newest pending alerts, up to a limit")
    sweep.add_argument("--limit", type=int, default=3)
    severity(sweep)
    sweep.add_argument("--dry-run", action="store_true", help="print the questions and stop")
    sweep.set_defaults(func=cmd_sweep)
    return parser


def main(argv: list[str] | None = None, services: Services | None = None) -> int:
    for out in (sys.stdout, sys.stderr):
        reconfigure = getattr(out, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    code: int = args.func(services or Services(settings=get_settings()), args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
