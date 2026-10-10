"""get_maintenance: the maintenance calendar. Future windows are visible, like a real calendar."""

from typing import Any

from pydantic import Field
from sqlalchemy import text

from incident_agent.agent.tools.common import (
    MAX_ROWS_CONSIDERED,
    Item,
    NodeIndex,
    assemble,
    error_result,
    join_ids,
    resolve_scope,
    trim,
)
from incident_agent.agent.tools.schema import ToolArgs
from incident_agent.agent.tools.timeutil import (
    TimeParseError,
    as_utc,
    fmt,
    fmt_duration,
    iso,
    parse_time,
)
from incident_agent.agent.types import EvidenceRef, ToolContext, ToolResult

FETCH_LIMIT = 300


class GetMaintenanceArgs(ToolArgs):
    start: str = Field(description="Range start, ISO 8601; no offset = Africa/Tunis local time.")
    end: str = Field(description="Range end, ISO 8601. Windows later than now are scheduled ones.")
    node_ids: list[str] | None = Field(
        default=None, max_length=12, description="Up to 12 node ids (sites, links, routers, core)."
    )
    region_id: str | None = Field(default=None, description="TUN, SAH, SFX or SUD.")
    include_ancestors: bool = Field(
        default=True,
        description="Also include windows on the parents of node_ids (link, router).",
    )


def get_maintenance(ctx: ToolContext, args: GetMaintenanceArgs) -> ToolResult:
    try:
        start, end = parse_time(args.start, name="start"), parse_time(args.end, name="end")
        if end < start:
            raise TimeParseError(f"end ({fmt(end)}) is before start ({fmt(start)}).")
    except TimeParseError as exc:
        return error_result("get_maintenance", args, str(exc))
    asked = as_utc(ctx.asked_at)

    with ctx.engine.connect() as conn:
        idx = NodeIndex.load(conn)
        scope = resolve_scope(idx, args.node_ids, args.region_id, ancestors=args.include_ancestors)
        if scope.error:
            return error_result("get_maintenance", args, scope.error)
        sql = [
            "SELECT mw_id, node_id, start_at, end_at, description, expected_impact "
            "FROM maintenance WHERE start_at <= :end AND end_at >= :start"
        ]
        params: dict[str, Any] = {"start": start, "end": end}
        if scope.ids is not None:
            sql.append("AND node_id = ANY(:nodes)")
            params["nodes"] = sorted(scope.ids)
        sql.append(f"ORDER BY start_at, mw_id LIMIT {FETCH_LIMIT}")
        rows = conn.execute(text(" ".join(sql)), params).all()

    where = (
        f"{join_ids(scope.direct, 4)}{' and its parents' if args.include_ancestors else ''}"
        if scope.direct
        else (f"region {args.region_id.upper()}" if args.region_id else "any node")
    )
    span = f"{fmt(start)} to {fmt(end)}"
    if not rows:
        body = " ".join(
            [
                f"No maintenance window scheduled on {where} between {fmt(start)} and {fmt(end)}.",
                *scope.notes,
            ]
        )
        return ToolResult(
            tool="get_maintenance",
            args=args.model_dump(),
            headline=body[:200],
            body=body,
            data={"n_total": 0, "rows": []},
        )

    items: list[Item] = []
    for r in rows:
        if r.end_at <= asked:
            state = "completed"
        elif r.start_at <= asked:
            state = "in progress"
        else:
            state = "planned"
        node = idx.nodes[r.node_id]
        reach = ""
        if node.node_type in ("transport_link", "agg_router", "core_upf"):
            sites = sum(1 for d in idx.descendants(r.node_id) if idx.nodes[d].node_type == "site")
            reach = f", covers {sites} sites below"
        rel = scope.label(r.node_id)
        timing = f"{fmt(r.start_at)} -> {fmt(r.end_at)}"
        if state == "planned":
            timing += f" (starts in {fmt_duration(r.start_at - asked)})"
        elif state == "in progress":
            timing += f" (ends in {fmt_duration(r.end_at - asked)})"
        desc = trim(r.description, 90)
        line = (
            f"{r.mw_id} {state.upper() if state != 'completed' else state} {timing} "
            f"on {r.node_id}{f' ({rel})' if rel else ''}{reach}: {desc}; "
            f"expected impact: {trim(r.expected_impact, 60)}"
        )
        items.append(
            Item(
                line=line,
                sort=(r.start_at, r.mw_id),
                ref=EvidenceRef(
                    ref=r.mw_id,
                    kind="maintenance",
                    summary=trim(
                        f"{state} window {timing} on {r.node_id}: {desc}; "
                        f"expected impact: {r.expected_impact}",
                        170,
                    ),
                ),
                data={
                    "mw_id": r.mw_id,
                    "node_id": r.node_id,
                    "start_at": iso(r.start_at),
                    "end_at": iso(r.end_at),
                    "description": r.description,
                    "expected_impact": r.expected_impact,
                    "state": state,
                    "relation": rel,
                },
            )
        )

    counts = {
        s: sum(1 for i in items if i.data["state"] == s)
        for s in ("in progress", "completed", "planned")
    }
    summary = ", ".join(f"{n} {s}" for s, n in counts.items() if n)
    head = [
        f"{len(rows)} maintenance window(s) on {where} overlap {span}: {summary} "
        f"(state as of asked_at {fmt(asked)})."
    ]
    if counts["planned"]:
        head.append("Planned windows are calendar entries that start after asked_at.")
    head += scope.notes
    ordered = sorted(
        items,
        key=lambda i: (
            i.data["state"] != "in progress",
            1 if i.data["relation"] else 0,
            abs(i.sort[0] - asked),
        ),
    )[:MAX_ROWS_CONSIDERED]
    out = assemble(
        head,
        ordered,
        omitted_line=lambda left: f"Omitted {len(left)} more window(s); narrow the range or nodes.",
    )
    return ToolResult(
        tool="get_maintenance",
        args=args.model_dump(),
        headline=head[0][:200],
        body=out.body,
        refs=out.refs,
        data={
            "window": [iso(start), iso(end)],
            "n_total": len(rows),
            "rows": [i.data for i in out.shown],
        },
        truncated=out.truncated,
    )
