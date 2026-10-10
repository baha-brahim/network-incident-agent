"""Command line: `python -m incident_agent.agent ask "..." --asked-at "2026-09-29 08:00"`.

ask        investigate a question and print the steps, the report and the usage totals
scenario   development aid: run planted scenarios and print the truth next to the verdict
scenarios  development aid: list scenario ids with kind and difficulty
"""

import argparse
import sys
from datetime import datetime
from typing import Any

from sqlalchemy import text

from incident_agent.agent.config import AgentConfig
from incident_agent.agent.graph import investigate
from incident_agent.agent.state import AgentEvent, RunResult
from incident_agent.agent.store import TraceStore
from incident_agent.agent.tools.timeutil import parse_time
from incident_agent.db.session import get_engine


def _short(value: Any, limit: int = 160) -> str:
    one = " ".join(str(value).split())
    return one if len(one) <= limit else one[: limit - 3] + "..."


def format_event(event: AgentEvent) -> str | None:
    d = event.data
    if event.type == "run_started":
        return f"== {event.run_id}: {_short(d['question'], 200)}"
    if event.type == "scope":
        where = ", ".join([*d["region_ids"], *d["node_ids"]]) or "no place named"
        return (
            f"scope: {d['symptom']} | {where} | {d['window_start'][:16]}Z to "
            f"{d['window_end'][:16]}Z{' (ongoing)' if d['ongoing'] else ''}"
            f"{' [default window]' if d['source'] == 'default' else ''}"
        )
    if event.type == "llm_call":
        who = f"{d['provider']}:{d['model']}" if not d["error"] else "FAILED"
        extra = (" cached" if d["cached"] else "") + (" FALLBACK" if d["fell_back"] else "")
        err = f" {_short(d['error'], 200)}" if d["error"] else ""
        return (
            f"  llm {d['purpose']}: {who} in={d['input_tokens']} out={d['output_tokens']} "
            f"{d['wall_ms'] / 1000:.1f}s{extra}{err}"
        )
    if event.type == "tool_result":
        err = " ERROR" if d["error"] else ""
        return f"  {d['ref']} {d['tool']}{err}: {_short(d['headline'], 170)}"
    if event.type == "note":
        return f"  note (turn {d['iteration']}): {_short(d['text'], 600)}"
    if event.type == "gate":
        return f"  gate: {d['message']}"
    if event.type == "error":
        return f"  ERROR in {d.get('where', 'run')}: {_short(d.get('message'), 300)}"
    return None


def print_result(result: RunResult) -> None:
    print()
    print(result.markdown)
    u = result.usage
    print("-" * 70)
    print(
        f"llm calls {u.llm_calls} ({u.cached_calls} cached) | tool calls {u.tool_calls} | "
        f"tokens in {u.input_tokens} out {u.output_tokens} | {u.wall_seconds:.1f}s"
    )
    print(f"models: {', '.join(result.models_used)}{'  [FELL BACK]' if result.fell_back else ''}")
    if u.live_requests:
        print(f"live requests: {u.live_requests}")
    if result.issues:
        print("issues: " + " | ".join(_short(i, 200) for i in result.issues))


def dataset_now() -> datetime:
    with get_engine().connect() as conn:
        value = conn.execute(text("SELECT value FROM dataset_meta WHERE key = 'now'")).scalar_one()
    return parse_time(str(value))


def _config(args: argparse.Namespace) -> AgentConfig:
    cfg = AgentConfig()
    if args.no_gate:
        cfg = cfg.model_copy(update={"completeness_gate": False})
    if args.max_iterations:
        cfg = cfg.model_copy(update={"max_iterations": args.max_iterations})
    return cfg


def _run(question: str, asked_at: datetime, args: argparse.Namespace) -> RunResult:
    store = None if args.no_store else TraceStore(get_engine())

    def show(event: AgentEvent) -> None:
        if not args.quiet and (line := format_event(event)):
            print(line, flush=True)

    return investigate(question, asked_at, store=store, config=_config(args), on_event=show)


def cmd_ask(args: argparse.Namespace) -> int:
    asked_at = parse_time(args.asked_at) if args.asked_at else dataset_now()
    result = _run(args.question, asked_at, args)
    print_result(result)
    return 0 if result.status == "finished" else 1


def cmd_scenarios(_: argparse.Namespace) -> int:
    from incident_agent.agent.scenario_dev import list_scenarios

    for s in list_scenarios(get_engine()):
        print(
            f"{s['scenario_id']}  {s['kind']:<22} {s['difficulty']:<7} {s['n_questions']} questions"
        )
    return 0


def cmd_scenario(args: argparse.Namespace) -> int:
    from incident_agent.agent.scenario_dev import compare, load_question, load_truth

    engine = get_engine()
    rows: list[str] = []
    for scenario_id in args.scenario_ids:
        question, asked_at = load_question(engine, scenario_id, args.question)
        result = _run(question, asked_at, args)
        if not args.quiet or len(args.scenario_ids) == 1:
            print_result(result)
        truth = load_truth(engine, scenario_id)
        cmp = compare(truth, result)
        print()
        print(f"[{scenario_id}]")
        print("\n".join(cmp.lines(truth, result)))
        u = result.usage
        rows.append(
            f"| {scenario_id} | {truth.kind} | {truth.difficulty} | "
            f"{'yes' if cmp.classification_ok else 'NO'} | {'yes' if cmp.category_ok else 'NO'} | "
            f"{'yes' if cmp.node_ok else 'NO'} | {result.report.confidence} | {u.llm_calls} | "
            f"{u.tool_calls} | {u.input_tokens + u.output_tokens} | {u.wall_seconds:.0f} | "
            f"{', '.join(result.models_used)} |"
        )
    if len(rows) > 1:
        print()
        print(
            "| scenario | kind | difficulty | classification | category | root node | confidence "
            "| LLM calls | tool calls | tokens | seconds | models |"
        )
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")
        print("\n".join(rows))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m incident_agent.agent", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--no-store", action="store_true", help="do not write the trace to the DB")
        p.add_argument("--no-gate", action="store_true", help="turn the completeness gate off")
        p.add_argument("--max-iterations", type=int, default=0)
        p.add_argument("--quiet", action="store_true", help="do not print the steps live")

    ask = sub.add_parser("ask", help="investigate a question")
    ask.add_argument("question")
    ask.add_argument(
        "--asked-at", help="the investigation's 'now', local time (default: the dataset's now)"
    )
    common(ask)
    ask.set_defaults(func=cmd_ask)

    scenario = sub.add_parser("scenario", help="development aid: run planted scenarios")
    scenario.add_argument("scenario_ids", nargs="+", metavar="SCN-001")
    scenario.add_argument("--question", type=int, default=0, help="which question of the scenario")
    common(scenario)
    scenario.set_defaults(func=cmd_scenario)

    listing = sub.add_parser("scenarios", help="development aid: list scenarios")
    listing.set_defaults(func=cmd_scenarios)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
