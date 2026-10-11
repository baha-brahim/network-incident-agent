"""get_external_events: stadium events, holidays, festivals, as known at `asked_at`."""

from typing import Any

from pydantic import Field
from sqlalchemy import text

from incident_agent.agent.tools.common import (
    MAX_ROWS_CONSIDERED,
    Item,
    assemble,
    error_result,
    trim,
)
from incident_agent.agent.tools.schema import END, REGION, START, ToolArgs
from incident_agent.agent.tools.timeutil import TimeParseError, fmt, iso, make_window
from incident_agent.agent.types import EvidenceRef, ToolContext, ToolResult

FETCH_LIMIT = 200


class GetExternalEventsArgs(ToolArgs):
    start: str = Field(description=START)
    end: str = Field(description=END)
    region_id: str | None = Field(default=None, description=REGION)


def get_external_events(ctx: ToolContext, args: GetExternalEventsArgs) -> ToolResult:
    try:
        window = make_window(args.start, args.end, ctx.asked_at)
    except TimeParseError as exc:
        return error_result("get_external_events", args, str(exc))
    asked = window.asked_at

    region = args.region_id.strip().upper() if args.region_id else None
    rows: list[Any] = []
    with ctx.engine.connect() as conn:
        known = {r[0] for r in conn.execute(text("SELECT region_id FROM regions"))}
        if region is not None and region not in known:
            return error_result(
                "get_external_events",
                args,
                f"Unknown region_id {region!r}. Regions: {', '.join(sorted(known))}.",
            )
        if not window.empty:
            sql = [
                "SELECT event_id, region_id, node_id, event_type, start_at, end_at, description "
                "FROM external_events WHERE start_at <= :end AND end_at >= :start"
            ]
            params: dict[str, Any] = {"start": window.start, "end": window.end}
            if region is not None:
                sql.append("AND (region_id IS NULL OR region_id = :region)")
                params["region"] = region
            sql.append(f"ORDER BY start_at, event_id LIMIT {FETCH_LIMIT}")
            rows = list(conn.execute(text(" ".join(sql)), params).all())

    where = f"region {region} (and nationwide)" if region else "all regions"
    notes = window.notes()
    if not rows:
        body = " ".join(
            [
                f"No external events for {where} between {fmt(window.start)} "
                f"and {fmt(window.end)}.",
                *notes,
            ]
        )
        return ToolResult(
            tool="get_external_events",
            args=args.model_dump(),
            headline=body[:200],
            body=body,
            data={"n_total": 0, "rows": []},
        )

    items: list[Item] = []
    for r in rows:
        ended = r.end_at <= asked
        timing = (
            f"{fmt(r.start_at)} -> {fmt(r.end_at)}"
            if ended
            else f"since {fmt(r.start_at)}, in progress"
        )
        scope = r.region_id or "nationwide"
        near = f", near {r.node_id}" if r.node_id else ""
        desc = trim(r.description, 100)
        items.append(
            Item(
                line=f"{r.event_id} {r.event_type} ({scope}{near}) {timing}: {desc}",
                sort=(r.start_at, r.event_id),
                ref=EvidenceRef(
                    ref=r.event_id,
                    kind="event",
                    summary=trim(f"{r.event_type} ({scope}{near}) {timing}: {desc}", 170),
                ),
                data={
                    "event_id": r.event_id,
                    "event_type": r.event_type,
                    "region_id": r.region_id,
                    "node_id": r.node_id,
                    "start_at": iso(r.start_at),
                    "end_at": iso(r.end_at) if ended else None,
                    "in_progress": not ended,
                    "description": r.description,
                },
            )
        )
    n_live = sum(1 for i in items if i.data["in_progress"])
    head = [
        f"{len(rows)} external event(s) for {where}, {fmt(window.start)} to "
        f"{fmt(window.end)}; {n_live} in progress at asked_at ({fmt(asked)})."
    ]
    head += notes
    ordered = sorted(items, key=lambda i: (not i.data["in_progress"], i.sort))[:MAX_ROWS_CONSIDERED]
    out = assemble(
        head,
        ordered,
        omitted_line=lambda left: f"Omitted {len(left)} more events; narrow the window.",
    )
    return ToolResult(
        tool="get_external_events",
        args=args.model_dump(),
        headline=head[0][:200],
        body=out.body,
        refs=out.refs,
        data={
            "window": [iso(window.start), iso(window.end)],
            "n_total": len(rows),
            "rows": [i.data for i in out.shown],
        },
        truncated=out.truncated,
    )
