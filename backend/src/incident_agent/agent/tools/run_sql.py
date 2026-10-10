"""run_sql: a last-resort read-only query, with the time-series tables clamped to `asked_at`.

How the clamp works: the query is not rewritten. It runs as a subquery below a `WITH` clause that
defines `cell_kpis`, `core_kpis`, `alarms`, `changes`, `maintenance` and `external_events` as
filtered copies of the real tables. A bare table name in the model's query therefore resolves to
the filtered copy. The guard (sqlguard) rejects every way of naming the real tables (schema
qualifiers, `pg_*` catalogs, quoted variants, non-allow-listed functions that run SQL text).
"""

import decimal
from datetime import date, datetime
from typing import Any

from pydantic import Field
from sqlalchemy.exc import DBAPIError

from incident_agent.agent.tools.common import BODY_CHARS, error_result, hard_cap, trim
from incident_agent.agent.tools.schema import ToolArgs
from incident_agent.agent.tools.sqlguard import GuardError, check_sql
from incident_agent.agent.tools.timeutil import LOCAL_TZ_NAME, as_utc, fmt, iso
from incident_agent.agent.types import ToolContext, ToolResult

ROW_CAP = 50
TIMEOUT = "5s"

TABLE_COLUMNS = {
    "cell_kpis": "ts, cell_id, dl_volume_mb, ul_volume_mb, active_users, rrc_success_pct, "
    "drop_rate_pct, latency_ms, prb_util_pct, availability_pct",
    "core_kpis": "ts, node_id, metric, value",
    "alarms": "alarm_id, node_id, alarm_type, severity, raised_at, cleared_at, description",
    "changes": "change_id, node_id, change_type, executed_at, description, ticket, status, "
    "rollback_of",
    "maintenance": "mw_id, node_id, start_at, end_at, description, expected_impact, status",
    "external_events": "event_id, region_id, node_id, event_type, start_at, end_at, description",
    "nodes": "node_id, node_type, name, region_id, parent_id, attrs",
    "cells": "cell_id, site_id, technology, sector, capacity_mbps",
    "regions": "region_id, name",
}


class RunSqlArgs(ToolArgs):
    query: str = Field(
        min_length=6,
        max_length=3000,
        description="One SELECT (or WITH ... SELECT) over the tables in the tool description.",
    )


def shadow_prefix(asked_at: datetime) -> str:
    """The WITH clause that hides everything after `asked_at`."""
    ts = as_utc(asked_at).strftime("%Y-%m-%d %H:%M:%S+00")
    t = f"TIMESTAMPTZ '{ts}'"
    return (
        "WITH "
        f"cell_kpis AS NOT MATERIALIZED (SELECT * FROM public.cell_kpis WHERE ts <= {t}), "
        f"core_kpis AS NOT MATERIALIZED (SELECT * FROM public.core_kpis WHERE ts <= {t}), "
        "alarms AS NOT MATERIALIZED (SELECT alarm_id, node_id, alarm_type, severity, raised_at, "
        f"CASE WHEN cleared_at <= {t} THEN cleared_at END AS cleared_at, description "
        f"FROM public.alarms WHERE raised_at <= {t}), "
        "changes AS NOT MATERIALIZED (SELECT c.change_id, c.node_id, c.change_type, c.executed_at, "
        "c.description, c.ticket, "
        "CASE WHEN c.status = 'rolled_back' AND (NOT EXISTS (SELECT 1 FROM public.changes r "
        "WHERE r.rollback_of = c.change_id) OR EXISTS (SELECT 1 FROM public.changes r "
        f"WHERE r.rollback_of = c.change_id AND r.executed_at <= {t})) "
        "THEN 'rolled_back' ELSE 'completed' END AS status, c.rollback_of "
        f"FROM public.changes c WHERE c.executed_at <= {t}), "
        "maintenance AS NOT MATERIALIZED (SELECT mw_id, node_id, start_at, end_at, description, "
        f"expected_impact, CASE WHEN end_at <= {t} THEN 'completed' "
        f"WHEN start_at <= {t} THEN 'in_progress' ELSE 'planned' END AS status "
        "FROM public.maintenance), "
        "external_events AS NOT MATERIALIZED (SELECT event_id, region_id, node_id, event_type, "
        f"start_at, CASE WHEN end_at <= {t} THEN end_at END AS end_at, description "
        f"FROM public.external_events WHERE start_at <= {t}) "
    )


def build_sql(user_sql: str, asked_at: datetime) -> str:
    return (
        f"{shadow_prefix(asked_at)}"
        f"SELECT _q.*, count(*) OVER () AS _total_rows FROM ({user_sql}) AS _q LIMIT {ROW_CAP}"
    )


def _cell(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, datetime):
        return fmt(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (float, decimal.Decimal)):
        number = float(value)
        return str(int(number)) if number.is_integer() and abs(number) < 1e12 else f"{number:.4g}"
    return trim(str(value), 48)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, (date, decimal.Decimal)):
        return str(value)
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


def _db_error(exc: DBAPIError, user_sql: str) -> str:
    message = str(exc.orig).strip().splitlines()[0] if exc.orig else "database error"
    if "statement timeout" in message:
        return (
            f"The query exceeded the {TIMEOUT} limit. Add filters (ts range, node ids) or "
            "aggregate in SQL."
        )
    hint = ""
    if "does not exist" in message or "syntax" in message:
        mentioned = [t for t in TABLE_COLUMNS if t in user_sql.lower()]
        names = mentioned or ["cell_kpis", "alarms", "nodes"]
        hint = " Columns: " + "; ".join(f"{t}({TABLE_COLUMNS[t]})" for t in names[:3]) + "."
    return trim(f"SQL error: {message}.{hint}", 600)


def run_sql(ctx: ToolContext, args: RunSqlArgs) -> ToolResult:
    try:
        user_sql = check_sql(args.query)
    except GuardError as exc:
        return error_result("run_sql", args, f"Query rejected: {exc}")

    sql = build_sql(user_sql, ctx.asked_at)
    try:
        with ctx.engine.connect() as conn:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = '{TIMEOUT}'")
            conn.exec_driver_sql("SET LOCAL lock_timeout = '1s'")
            conn.exec_driver_sql(f"SET LOCAL TIME ZONE '{LOCAL_TZ_NAME}'")
            result = conn.execution_options(no_parameters=True).exec_driver_sql(sql)
            columns = [str(k) for k in result.keys()][:-1]  # noqa: SIM118
            raw = [tuple(r) for r in result.fetchall()]
    except DBAPIError as exc:
        return error_result("run_sql", args, _db_error(exc, user_sql))
    total = int(raw[0][-1]) if raw else 0
    rows = [r[:-1] for r in raw]
    return _format(args, columns, rows, total, ctx)


def _format(
    args: RunSqlArgs,
    columns: list[str],
    rows: list[tuple[Any, ...]],
    total: int,
    ctx: ToolContext,
) -> ToolResult:
    note = f"(tables clamped to asked_at {fmt(ctx.asked_at)}; times local)"
    if not rows:
        body = f"0 rows. {note}"
        return ToolResult(
            tool="run_sql",
            args=args.model_dump(),
            headline="run_sql: 0 rows",
            body=body,
            data={"columns": columns, "rows": [], "total_rows": 0},
        )
    lines = [" | ".join(columns)] + [" | ".join(_cell(v) for v in row) for row in rows]
    cap = f", first {len(rows)} returned" if total > len(rows) else ""
    lead = f"{total} row(s){cap} {note}"
    budget = BODY_CHARS - len(lead) - 120
    shown: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > budget and len(shown) > 1:
            break
        shown.append(trim(line, 400) if not shown else line)
        used += len(line) + 1
    shown_rows = len(shown) - 1
    truncated = shown_rows < total
    tail = []
    if truncated:
        tail.append(
            f"Showing {shown_rows} of {total} rows (row cap {ROW_CAP}, body budget); "
            "aggregate or add LIMIT/filters for the rest."
        )
    body = hard_cap("\n".join([lead, *shown, *tail]))
    return ToolResult(
        tool="run_sql",
        args=args.model_dump(),
        headline=f"run_sql: {total} row(s), columns {', '.join(columns)}"[:200],
        body=body,
        data={
            "columns": columns,
            "rows": [[_json_safe(v) for v in row] for row in rows],
            "total_rows": total,
        },
        truncated=truncated,
    )
