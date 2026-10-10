"""get_alarms: alarms active or raised in a window, as they were known at `asked_at`."""

from datetime import timedelta
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import text

from incident_agent.agent.tools.common import (
    MAX_ROWS_CONSIDERED,
    Item,
    NodeIndex,
    assemble,
    count_by,
    error_result,
    join_ids,
    resolve_scope,
)
from incident_agent.agent.tools.schema import ToolArgs
from incident_agent.agent.tools.timeutil import TimeParseError, fmt, fmt_hm, iso, make_window
from incident_agent.agent.types import EvidenceRef, ToolContext, ToolResult

SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2, "warning": 3}
FETCH_LIMIT = 1000
GROUP_ABOVE = 10  # more alarms than this: minor and warning ones are grouped per node and type
SELF_CLEARING = timedelta(minutes=10)


class GetAlarmsArgs(ToolArgs):
    start: str = Field(description="Window start, ISO 8601; no offset = Africa/Tunis local time.")
    end: str = Field(description="Window end, ISO 8601. Anything after the current time is cut.")
    node_ids: list[str] | None = Field(
        default=None, max_length=12, description="Nodes to look at (sites, links, routers, core)."
    )
    region_id: str | None = Field(default=None, description="TUN, SAH, SFX or SUD.")
    include_descendants: bool = Field(
        default=True, description="Also include alarms on the nodes below node_ids."
    )
    min_severity: Literal["warning", "minor", "major", "critical"] | None = Field(
        default=None, description="Hide alarms below this severity."
    )
    alarm_types: list[str] | None = Field(default=None, max_length=8, description="e.g. LINK_LOS.")


def _scope_text(direct: list[str], region_id: str | None, below: bool) -> str:
    if direct:
        return f"{join_ids(direct, 4)}{' and nodes below' if below else ''}"
    if region_id:
        return f"region {region_id.upper()}"
    return "any node"


def get_alarms(ctx: ToolContext, args: GetAlarmsArgs) -> ToolResult:
    try:
        window = make_window(args.start, args.end, ctx.asked_at)
    except TimeParseError as exc:
        return error_result("get_alarms", args, str(exc))

    with ctx.engine.connect() as conn:
        idx = NodeIndex.load(conn)
        scope = resolve_scope(
            idx, args.node_ids, args.region_id, descendants=args.include_descendants
        )
        if scope.error:
            return error_result("get_alarms", args, scope.error)
        if window.empty:
            return _empty(args, window.notes(), scope.notes, "", [])

        sql = [
            "SELECT alarm_id, node_id, alarm_type, severity, raised_at, cleared_at "
            "FROM alarms WHERE raised_at <= :end AND (cleared_at IS NULL OR cleared_at >= :start)"
        ]
        params: dict[str, Any] = {"start": window.start, "end": window.end}
        if scope.ids is not None:
            sql.append("AND node_id = ANY(:nodes)")
            params["nodes"] = sorted(scope.ids)
        if args.min_severity:
            keep = [s for s, r in SEVERITY_RANK.items() if r <= SEVERITY_RANK[args.min_severity]]
            sql.append("AND severity = ANY(:severities)")
            params["severities"] = keep
        if args.alarm_types:
            sql.append("AND alarm_type = ANY(:types)")
            params["types"] = [t.strip().upper() for t in args.alarm_types]
        sql.append(f"ORDER BY raised_at, alarm_id LIMIT {FETCH_LIMIT + 1}")
        rows = list(conn.execute(text(" ".join(sql)), params).all())

    capped = len(rows) > FETCH_LIMIT
    rows = rows[:FETCH_LIMIT]
    notes = window.notes() + scope.notes
    scope_text = _scope_text(scope.direct, args.region_id, args.include_descendants)
    if not rows:
        return _empty(args, notes, [], scope_text, [fmt(window.start), fmt(window.end)])

    asked = window.asked_at
    items: list[Item] = []
    for r in rows:
        active = r.cleared_at is None or r.cleared_at > asked
        state = "active" if active else f"cleared {fmt(r.cleared_at)}"
        rel = scope.label(r.node_id)
        line = (
            f"{fmt(r.raised_at)} {r.alarm_id} {r.severity} {r.alarm_type} {r.node_id}"
            f"{f' ({rel})' if rel else ''}: {state}"
        )
        summary = f"{r.severity} {r.alarm_type} on {r.node_id}, raised {fmt(r.raised_at)}, {state}"
        items.append(
            Item(
                line=line,
                sort=(r.raised_at, r.alarm_id),
                ref=EvidenceRef(ref=r.alarm_id, kind="alarm", summary=summary),
                data={
                    "alarm_id": r.alarm_id,
                    "node_id": r.node_id,
                    "alarm_type": r.alarm_type,
                    "severity": r.severity,
                    "raised_at": iso(r.raised_at),
                    "cleared_at": None if active else iso(r.cleared_at),
                    "active": active,
                },
            )
        )

    n_rows = len(items)
    if n_rows > GROUP_ABOVE:
        items = _collapse(items, asked)
    by_sev = {s: sum(1 for r in rows if r.severity == s) for s in SEVERITY_RANK}
    n_active = sum(1 for r in rows if r.cleared_at is None or r.cleared_at > asked)
    sev_text = ", ".join(f"{n} {s}" for s, n in by_sev.items() if n)
    count_text = f"{len(rows)}{'+' if capped else ''}"
    head = [
        f"{count_text} alarm(s) on {scope_text}, {fmt(window.start)} to {fmt(window.end)}: "
        f"{sev_text}; {n_active} active at asked_at ({fmt(asked)})."
    ]
    head.append(_earliest_serious(rows) or _no_serious(rows, asked))
    head += notes
    if capped:
        head.append(f"More than {FETCH_LIMIT} alarms matched; narrow the window or nodes.")

    ordered = sorted(
        items,
        key=lambda i: (SEVERITY_RANK[i.data["severity"]], -i.data.get("count", 1), i.sort),
    )[:MAX_ROWS_CONSIDERED]
    out = assemble(
        head,
        ordered,
        omitted_line=lambda left: (
            f"Omitted {len(left)} lower-priority alarms ({count_by(left, 'alarm_type')}); "
            "narrow the window or use min_severity / alarm_types to see them."
        ),
    )
    return ToolResult(
        tool="get_alarms",
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


def _no_serious(rows: list[Any], asked: Any) -> str:
    text_ = "No critical or major alarm in this window."
    short = sum(
        1
        for r in rows
        if r.cleared_at is not None
        and r.cleared_at <= asked
        and r.cleared_at - r.raised_at <= SELF_CLEARING
    )
    if len(rows) >= 5 and short * 2 >= len(rows):
        text_ += f" {short} of {len(rows)} cleared within 10 min of being raised (self-clearing)."
    return text_


def _collapse(items: list[Item], asked: Any) -> list[Item]:
    """Keep critical/major alarms as rows; fold the rest into one row per node, type, severity."""
    keep = [i for i in items if i.data["severity"] in ("critical", "major")]
    groups: dict[tuple[str, str, str], list[Item]] = {}
    for i in items:
        if i.data["severity"] not in ("critical", "major"):
            key = (i.data["node_id"], i.data["alarm_type"], i.data["severity"])
            groups.setdefault(key, []).append(i)
    for (node, kind, sev), members in groups.items():
        if len(members) == 1:
            keep.append(members[0])
            continue
        members.sort(key=lambda i: i.sort)
        first, last = members[0], members[-1]
        n_active = sum(1 for m in members if m.data["active"])
        span = fmt(first.sort[0])
        if last.sort[0].date() == first.sort[0].date():
            span += f" .. {fmt_hm(last.sort[0])}"
        else:
            span += f" .. {fmt(last.sort[0])}"
        state = f"{n_active} still active" if n_active else "all cleared"
        line = (
            f"{span} {sev} {kind} {node} x{len(members)} (e.g. {first.data['alarm_id']}): {state}"
        )
        ref = EvidenceRef(
            ref=first.data["alarm_id"],
            kind="alarm",
            summary=f"{sev} {kind} on {node}, {len(members)} occurrences from {span}; {state}",
        )
        keep.append(
            Item(
                line=line,
                sort=first.sort,
                ref=ref,
                data={
                    "group": True,
                    "count": len(members),
                    "alarm_id": first.data["alarm_id"],
                    "alarm_ids": [m.data["alarm_id"] for m in members],
                    "node_id": node,
                    "alarm_type": kind,
                    "severity": sev,
                    "raised_at": first.data["raised_at"],
                    "last_raised_at": last.data["raised_at"],
                    "n_active": n_active,
                    "active": n_active > 0,
                },
            )
        )
    return keep


def _earliest_serious(rows: list[Any]) -> str | None:
    """'Earliest critical/major: ... then ...': the line that usually settles root cause order."""
    serious = [r for r in rows if r.severity in ("critical", "major")]
    if not serious:
        return None
    first = serious[0]
    follow: dict[str, list[str]] = {}
    for r in serious[1:]:
        if r.raised_at - first.raised_at <= timedelta(minutes=10):
            follow.setdefault(r.alarm_type, []).append(r.node_id)
    text_ = (
        f"Earliest critical/major: {fmt(first.raised_at)} {first.alarm_type} "
        f"on {first.node_id} ({first.alarm_id})"
    )
    if follow:
        parts = [f"{t} x{len(n)} ({join_ids(n, 3)})" for t, n in follow.items()]
        text_ += "; within 10 min after: " + ", ".join(parts)
    return text_ + "."


def _empty(
    args: GetAlarmsArgs, notes: list[str], more: list[str], scope_text: str, span: list[str]
) -> ToolResult:
    where = f"No alarms on {scope_text} between {span[0]} and {span[1]}." if span else ""
    body = " ".join(part for part in [where, *notes, *more] if part) or "No alarms found."
    return ToolResult(
        tool="get_alarms",
        args=args.model_dump(),
        headline=body[:200],
        body=body,
        data={"n_total": 0, "rows": []},
    )
