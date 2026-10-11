"""Record an investigation as a replayable demo.

    python -m incident_agent.api.record --id fiber-cut          # the catalog's question and time
    python -m incident_agent.api.record --all
    python -m incident_agent.api.record --id my-demo --title "..." --teaser "..." \
        --question "..." --asked-at "2026-09-22T07:38:00Z"

Run it with `LLM_CACHE_MODE=replay` to reuse cached model responses; it refuses to run with the
cache off unless `--live` is given.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from incident_agent.agent.graph import stream
from incident_agent.agent.reference import Reference
from incident_agent.agent.tools import execute_tool
from incident_agent.agent.tools.timeutil import parse_time
from incident_agent.agent.types import ToolContext
from incident_agent.api.catalog import BY_ID, CATALOG, DemoSpec
from incident_agent.api.demos import DEMOS_DIR, counts_of, retime
from incident_agent.api.enrich import ToolRecorder
from incident_agent.api.events import ApiEvent, dumps
from incident_agent.api.kpis import charts_for
from incident_agent.api.runs import run_events
from incident_agent.api.schemas import Recording
from incident_agent.config import get_settings
from incident_agent.db.session import get_agent_engine
from incident_agent.llm.runner import LLMRunner


def capture(question: str, asked_at: datetime, *, allow_live: bool = False) -> list[ApiEvent]:
    """Run one investigation and return its API events (with the clock of this run)."""
    settings = get_settings()
    if settings.llm_cache_mode == "off" and not allow_live:
        raise SystemExit(
            "LLM_CACHE_MODE is 'off': this would call the model. Use LLM_CACHE_MODE=replay, "
            "or pass --live."
        )
    engine = get_agent_engine()
    recorder = ToolRecorder(execute_tool, charts_for)
    events = list(
        run_events(
            lambda: stream(
                question,
                asked_at,
                runner=LLMRunner("agent"),
                ctx=ToolContext(engine=engine, asked_at=asked_at),
                reference=Reference.load(engine),
                tool_executor=recorder,
            ),
            recorder,
        )
    )
    finished = events[-1]
    if finished["type"] != "run_finished" or finished["data"]["status"] != "finished":
        errors = [e["data"].get("message") for e in events if e["type"] == "error"]
        raise SystemExit(
            f"the investigation did not finish: {errors or finished['data']['issues']}"
        )
    return events


def write_demo(path: Path, meta: dict[str, Any], events: list[ApiEvent]) -> None:
    """One line per field and per event, so a changed recording shows as a readable diff."""
    head = [f'  "{key}": {dumps(value)}' for key, value in meta.items()]
    body = ",\n".join(f"    {dumps(event)}" for event in events)
    text = "{\n" + ",\n".join(head) + ',\n  "events": [\n' + body + "\n  ]\n}\n"
    path.write_bytes(text.encode("utf-8"))


def record(spec: DemoSpec, out_dir: Path, *, allow_live: bool = False) -> Recording:
    asked_at = parse_time(spec.asked_at)
    events = retime(capture(spec.question, asked_at, allow_live=allow_live))
    meta: dict[str, Any] = {
        "schema_version": 1,
        "id": spec.id,
        "title": spec.title,
        "teaser": spec.teaser,
        "question": spec.question,
        "asked_at": asked_at.isoformat(),
        "duration_ms": events[-1]["t_ms"],
        "counts": counts_of(events).model_dump(),
    }
    recording = Recording.model_validate({**meta, "events": events})  # fail before writing
    out_dir.mkdir(parents=True, exist_ok=True)
    write_demo(out_dir / f"{spec.id}.json", meta, events)
    return recording


def main(argv: list[str] | None = None) -> int:
    for out in (sys.stdout, sys.stderr):
        reconfigure = getattr(out, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="python -m incident_agent.api.record", description=__doc__
    )
    parser.add_argument("--id", help="demo id; known ids take their texts from the catalog")
    parser.add_argument("--all", action="store_true", help="record every demo of the catalog")
    parser.add_argument("--title")
    parser.add_argument("--teaser")
    parser.add_argument("--question")
    parser.add_argument("--asked-at", help="ISO 8601; without an offset, Africa/Tunis local time")
    parser.add_argument("--out-dir", type=Path, default=DEMOS_DIR)
    parser.add_argument("--live", action="store_true", help="allow model calls (cache mode off)")
    args = parser.parse_args(argv)

    if args.all:
        specs = list(CATALOG)
    elif args.id:
        base = BY_ID.get(args.id)
        fields = {
            "title": args.title or (base.title if base else None),
            "teaser": args.teaser or (base.teaser if base else None),
            "question": args.question or (base.question if base else None),
            "asked_at": args.asked_at or (base.asked_at if base else None),
        }
        missing = [name for name, value in fields.items() if not value]
        if missing:
            parser.error(f"unknown id {args.id!r}: also give {', '.join(missing)}")
        specs = [DemoSpec(args.id, **{k: str(v) for k, v in fields.items()})]
    else:
        parser.error("give --id or --all")

    for spec in specs:
        recording = record(spec, args.out_dir, allow_live=args.live)
        print(
            f"{spec.id}: {recording.counts.events} events, "
            f"{recording.counts.tool_calls} tool calls, replay {recording.duration_ms / 1000:.1f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
