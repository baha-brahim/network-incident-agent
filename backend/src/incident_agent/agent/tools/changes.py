"""get_changes: configuration and software changes, with rollbacks as known at `asked_at`."""

from typing import Any

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
    trim,
)
from incident_agent.agent.tools.schema import END, NODE_IDS, REGION, START, UNLISTED, ToolArgs
from incident_agent.agent.tools.timeutil import TimeParseError, fmt, iso, make_window
from incident_agent.agent.types import EvidenceRef, ToolContext, ToolResult

FETCH_LIMIT = 500
_TYPE_PRIORITY = {"rollback": 0, "config_push": 1, "software_upgrade": 1, "parameter_tuning": 2}


class GetChangesArgs(ToolArgs):
    start: str = Field(description=START)
    end: str = Field(description=END)
    node_ids: list[str] | None = Field(default=None, max_length=12, description=NODE_IDS)
    region_id: str | None = Field(default=None, description=REGION)
    include_ancestors: bool = Field(
        default=True, description="Include parents.", json_schema_extra=UNLISTED
    )


def get_changes(ctx: ToolContext, args: GetChangesArgs) -> ToolResult:
    try:
        window = make_window(args.start, args.end, ctx.asked_at)
    except TimeParseError as exc:
        return error_result("get_changes", args, str(exc))

    with ctx.engine.connect() as conn:
        idx = NodeIndex.load(conn)
        scope = resolve_scope(idx, args.node_ids, args.region_id, ancestors=args.include_ancestors)
        if scope.error:
            return error_result("get_changes", args, scope.error)
        rows: list[Any] = []
        rollbacks: dict[str, list[Any]] = {}
        if not window.empty:
            sql = [
                "SELECT change_id, node_id, change_type, executed_at, description, status, "
                "rollback_of FROM changes WHERE executed_at >= :start AND executed_at <= :end"
            ]
            params: dict[str, Any] = {"start": window.start, "end": window.end}
            if scope.ids is not None:
                sql.append("AND node_id = ANY(:nodes)")
                params["nodes"] = sorted(scope.ids)
            sql.append(f"ORDER BY executed_at, change_id LIMIT {FETCH_LIMIT}")
            rows = list(conn.execute(text(" ".join(sql)), params).all())
            if rows:
                found = conn.execute(
                    text(
                        "SELECT change_id, rollback_of, executed_at FROM changes "
                        "WHERE rollback_of = ANY(:ids)"
                    ),
                    {"ids": [r.change_id for r in rows]},
                ).all()
                for f in found:
                    rollbacks.setdefault(f.rollback_of, []).append(f)

    notes = window.notes() + scope.notes
    where = (
        f"{join_ids(scope.direct, 4)}{' and its parents' if args.include_ancestors else ''}"
        if scope.direct
        else (f"region {args.region_id.upper()}" if args.region_id else "any node")
    )
    if not rows:
        body = " ".join(
            [f"No changes on {where} between {fmt(window.start)} and {fmt(window.end)}.", *notes]
        )
        return ToolResult(
            tool="get_changes",
            args=args.model_dump(),
            headline=body[:200],
            body=body,
            data={"n_total": 0, "rows": []},
        )

    asked = window.asked_at
    items: list[Item] = []
    for r in rows:
        state, rolled_back = _state(r, rollbacks.get(r.change_id, []), asked, fmt)
        rel = scope.label(r.node_id)
        desc = trim(r.description, 80)
        what = f"rollback of {r.rollback_of}" if r.rollback_of else r.change_type
        line = (
            f"{fmt(r.executed_at)} {r.change_id} {what} on {r.node_id}"
            f"{f' ({rel})' if rel else ''}: {desc}"
            f"{f' -> {state}' if state else ''}"
        )
        items.append(
            Item(
                line=line,
                sort=(r.executed_at, r.change_id),
                ref=EvidenceRef(
                    ref=r.change_id,
                    kind="change",
                    summary=trim(f"{what} on {r.node_id} at {fmt(r.executed_at)}: {desc}", 150)
                    + (f" [{state}]" if state else ""),
                ),
                data={
                    "change_id": r.change_id,
                    "node_id": r.node_id,
                    "change_type": r.change_type,
                    "executed_at": iso(r.executed_at),
                    "description": r.description,
                    "rollback_of": r.rollback_of,
                    "rolled_back": rolled_back,
                    "relation": rel,
                },
            )
        )

    n_rb = sum(1 for i in items if i.data["rolled_back"])
    n_up = sum(1 for i in items if i.data["relation"])
    head = [
        f"{len(rows)} change(s) on {where}, {fmt(window.start)} to {fmt(window.end)} "
        f"({n_up} on upstream nodes, {n_rb} rolled back by asked_at {fmt(asked)})."
    ]
    head += notes
    ordered = sorted(
        items,
        key=lambda i: (
            1 if i.data["relation"] else 0,
            _TYPE_PRIORITY.get(i.data["change_type"], 3),
            -i.sort[0].timestamp(),
        ),
    )[:MAX_ROWS_CONSIDERED]
    out = assemble(
        head,
        ordered,
        omitted_line=lambda left: (
            f"Omitted {len(left)} lower-priority changes ({count_by(left, 'change_type')}); "
            "narrow the window or nodes to see them."
        ),
    )
    return ToolResult(
        tool="get_changes",
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


def _state(row: Any, rollbacks: list[Any], asked: Any, fmt_fn: Any) -> tuple[str, bool]:
    """Status of a change as of `asked_at`: a rollback that happens later is not visible."""
    if row.rollback_of:
        return "", False
    if row.status != "rolled_back":
        return "", False
    if not rollbacks:  # marked rolled back but no rollback record exists: trust the status
        return "ROLLED BACK (time unknown)", True
    done = sorted(
        (rb for rb in rollbacks if rb.executed_at <= asked), key=lambda rb: rb.executed_at
    )
    if done:
        return f"ROLLED BACK by {done[0].change_id} at {fmt_fn(done[0].executed_at)}", True
    return "in effect (not rolled back)", False
