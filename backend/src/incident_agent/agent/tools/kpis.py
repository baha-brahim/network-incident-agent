"""query_kpis: KPI series with a baseline from earlier days, onset and recovery of deviations."""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import Field
from sqlalchemy import Connection, text

from incident_agent.agent.tools.baseline import (
    LEAD_IN,
    MIN_HISTORY_DAYS,
    THIN_HISTORY_DAYS,
    Analysis,
    Floors,
    analyse,
    day_type,
    isodow_values,
)
from incident_agent.agent.tools.common import (
    BODY_CHARS,
    NodeIndex,
    error_result,
    hard_cap,
    join_ids,
    num,
    pct,
)
from incident_agent.agent.tools.schema import ToolArgs
from incident_agent.agent.tools.timeutil import (
    LOCAL_TZ,
    LOCAL_TZ_NAME,
    TimeParseError,
    fmt,
    fmt_duration,
    iso,
    make_window,
)
from incident_agent.agent.types import ToolContext, ToolResult
from incident_agent.detector.config import CELL_METRICS, CORE_METRICS

LOOKBACK_DAYS = 28  # history fetched before the window, for the baseline
MAX_POINTS = 12
EntityType = Literal["cell", "site", "region", "national", "core_node"]

# Weighted quality KPIs: traffic-weighted over the cells that reported (NULL while a cell is down).
_W = "SUM(k.{c} * k.dl_volume_mb) / NULLIF(SUM(k.dl_volume_mb) FILTER (WHERE k.{c} IS NOT NULL), 0)"
_AGG: dict[str, str] = {
    "dl_volume_mb": "SUM(k.dl_volume_mb)",
    "ul_volume_mb": "SUM(k.ul_volume_mb)",
    "active_users": "SUM(k.active_users)",
    "rrc_success_pct": f"COALESCE({_W.format(c='rrc_success_pct')}, AVG(k.rrc_success_pct))",
    "drop_rate_pct": f"COALESCE({_W.format(c='drop_rate_pct')}, AVG(k.drop_rate_pct))",
    "latency_ms": f"COALESCE({_W.format(c='latency_ms')}, AVG(k.latency_ms))",
    "prb_util_pct": "AVG(k.prb_util_pct)",
    "availability_pct": "AVG(k.availability_pct)",
    "cells_down": "COUNT(*) FILTER (WHERE k.availability_pct < 50)",
}
CELL_LEVEL_METRICS = list(_AGG)
_FLOORS: dict[str, Floors] = {
    m.name: Floors(m.abs_floor, m.rel_floor) for m in (*CELL_METRICS, *CORE_METRICS)
}
_FLOORS["ul_volume_mb"] = _FLOORS["dl_volume_mb"]
_FLOORS["cells_down"] = Floors(abs_floor=0.5)


class QueryKpisArgs(ToolArgs):
    entity_type: EntityType = Field(
        description="cell, site, region, national (everything) or core_node (DNS, UPF, AMF)."
    )
    entity_ids: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Up to 6 ids of that type. Not needed for national.",
    )
    metrics: list[str] = Field(
        min_length=1,
        max_length=4,
        description=(
            "Up to 4 metrics. Cell/site/region/national: dl_volume_mb, ul_volume_mb, active_users, "
            "rrc_success_pct, drop_rate_pct, latency_ms, prb_util_pct, availability_pct, "
            "cells_down. Core nodes: their own (e.g. query_success_pct, resolution_ms)."
        ),
    )
    start: str = Field(description="Window start, ISO 8601; no offset = Africa/Tunis local time.")
    end: str = Field(description="Window end, ISO 8601. Anything after the current time is cut.")


# --- data access -----------------------------------------------------------------------------


def _resolve_entities(
    conn: Connection, idx: NodeIndex, args: QueryKpisArgs
) -> tuple[list[str], list[str], str | None]:
    """(valid ids, notes, error)."""
    if args.entity_type == "national":
        return ["NATIONAL"], [], None
    if not args.entity_ids:
        return [], [], f"entity_ids is required for entity_type={args.entity_type}."
    ids: list[str] = []
    notes: list[str] = []
    for raw in args.entity_ids:
        key = raw.strip()
        key = key if key in idx.nodes or key in idx.cells or key in idx.regions else key.upper()
        ok = False
        if args.entity_type == "cell":
            ok = key in idx.cells
        elif args.entity_type == "region":
            ok = key in idx.regions
        elif args.entity_type == "site":
            ok = key in idx.nodes and idx.nodes[key].node_type == "site"
        else:
            ok = key in idx.nodes and idx.nodes[key].node_type.startswith("core_")
        if ok:
            if key not in ids:
                ids.append(key)
            continue
        notes.append(_why_not(idx, key, args.entity_type, raw))
    if not ids:
        return [], notes, " ".join(notes)
    return ids, notes, None


def _why_not(idx: NodeIndex, key: str, entity_type: str, raw: str) -> str:
    if key in idx.nodes:
        node = idx.nodes[key]
        hint = ""
        if node.node_type in ("transport_link", "agg_router"):
            sites = [d for d in idx.descendants(key) if idx.nodes[d].node_type == "site"]
            hint = f" Query its sites instead: {join_ids(sites)}."
        return (
            f"{raw} is a {node.node_type}, not a valid {entity_type} id; KPIs exist for cells, "
            f"sites, regions, national and core nodes.{hint}"
        )
    if key in idx.cells:
        return f"{raw} is a cell; use entity_type=cell (or its site {idx.cells[key]})."
    if key in idx.regions:
        return f"{raw} is a region; use entity_type=region."
    return f"Unknown {entity_type} id {raw!r}.{idx.suggest(raw)}"


def _core_metric_names(conn: Connection, ids: list[str]) -> dict[str, list[str]]:
    rows = conn.execute(
        text("SELECT DISTINCT node_id, metric FROM core_kpis WHERE node_id = ANY(:ids)"),
        {"ids": ids},
    )
    out: dict[str, list[str]] = {i: [] for i in ids}
    for r in rows:
        out[r.node_id].append(r.metric)
    return {k: sorted(v) for k, v in out.items()}


def _fetch_cell_level(
    conn: Connection,
    entity_type: str,
    ids: list[str],
    metrics: list[str],
    lo: datetime,
    lead: datetime,
    hi: datetime,
    dows: list[int],
) -> dict[tuple[str, str], pd.Series]:
    key, join, where = {
        "cell": ("k.cell_id", "", "k.cell_id = ANY(:ids)"),
        "site": ("c.site_id", "JOIN cells c ON c.cell_id = k.cell_id", "c.site_id = ANY(:ids)"),
        "region": (
            "n.region_id",
            "JOIN cells c ON c.cell_id = k.cell_id JOIN nodes n ON n.node_id = c.site_id",
            "n.region_id = ANY(:ids)",
        ),
        "national": ("'NATIONAL'", "", "TRUE"),
    }[entity_type]
    cols = ", ".join(f"{_AGG[m]} AS {m}" for m in metrics)
    sql = (
        f"SELECT {key} AS entity, k.ts, {cols} FROM cell_kpis k {join} "
        f"WHERE {where} AND k.ts >= :lo AND k.ts <= :hi "
        f"AND (k.ts >= :lead OR EXTRACT(ISODOW FROM k.ts AT TIME ZONE '{LOCAL_TZ_NAME}') "
        "= ANY(:dows)) GROUP BY 1, 2 ORDER BY 1, 2"
    )
    params: dict[str, Any] = {"lo": lo, "lead": lead, "hi": hi, "dows": dows}
    if entity_type != "national":
        params["ids"] = ids
    frame = pd.DataFrame(conn.execute(text(sql), params).all(), columns=["entity", "ts", *metrics])
    out: dict[tuple[str, str], pd.Series] = {}
    for entity, grp in frame.groupby("entity"):
        index = pd.DatetimeIndex(pd.to_datetime(grp["ts"], utc=True))
        for m in metrics:
            out[(str(entity), m)] = pd.Series(grp[m].astype(float).to_numpy(), index=index)
    return out


def _fetch_core(
    conn: Connection,
    ids: list[str],
    metrics: list[str],
    lo: datetime,
    lead: datetime,
    hi: datetime,
    dows: list[int],
) -> dict[tuple[str, str], pd.Series]:
    sql = (
        "SELECT node_id, metric, ts, value FROM core_kpis "
        "WHERE node_id = ANY(:ids) AND metric = ANY(:metrics) AND ts >= :lo AND ts <= :hi "
        f"AND (ts >= :lead OR EXTRACT(ISODOW FROM ts AT TIME ZONE '{LOCAL_TZ_NAME}') "
        "= ANY(:dows)) ORDER BY node_id, metric, ts"
    )
    rows = conn.execute(
        text(sql),
        {"ids": ids, "metrics": metrics, "lo": lo, "lead": lead, "hi": hi, "dows": dows},
    ).all()
    frame = pd.DataFrame(rows, columns=["node_id", "metric", "ts", "value"])
    out: dict[tuple[str, str], pd.Series] = {}
    for (node, metric), grp in frame.groupby(["node_id", "metric"]):
        index = pd.DatetimeIndex(pd.to_datetime(grp["ts"], utc=True))
        out[(str(node), str(metric))] = pd.Series(
            grp["value"].astype(float).to_numpy(), index=index
        )
    return out


# --- summarising one series ------------------------------------------------------------------


@dataclass
class PairSummary:
    entity: str
    metric: str
    a: Analysis
    n_steps: int = 0
    n_no_data: int = 0
    no_data_first: datetime | None = None
    no_data_last: datetime | None = None
    mean: float | None = None
    low: float | None = None
    low_at: datetime | None = None
    high: float | None = None
    high_at: datetime | None = None
    base_mean: float | None = None
    deviation_pct: float | None = None
    max_hist_days: int = 0
    onset: datetime | None = None
    recovery: datetime | None = None
    direction: str | None = None
    ongoing: bool = False
    before_window: bool = False
    worst_value: float | None = None
    worst_base: float | None = None
    worst_at: datetime | None = None
    last_step: datetime | None = None
    bucket_steps: int = 1
    series: list[float | None] = field(default_factory=list)
    base_series: list[float | None] = field(default_factory=list)
    series_start: datetime | None = None


def _ts(a: Analysis, i: int) -> datetime:
    return a.index[i].to_pydatetime()


def _bucket(values: np.ndarray, size: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(0, len(values), size):
        chunk = values[i : i + size]
        chunk = chunk[~np.isnan(chunk)]
        out.append(float(chunk.mean()) if chunk.size else None)
    return out


def summarise(entity: str, metric: str, a: Analysis) -> PairSummary:
    s = PairSummary(entity, metric, a)
    w = a.in_window
    vals, base, idx = a.values[w], a.baseline[w], a.index[w]
    s.n_steps = len(vals)
    if s.n_steps == 0:
        return s
    s.last_step = idx[-1].to_pydatetime()
    missing = np.isnan(vals)
    s.n_no_data = int(missing.sum())
    if s.n_no_data:
        gone = np.flatnonzero(missing)
        s.no_data_first, s.no_data_last = (
            idx[gone[0]].to_pydatetime(),
            idx[gone[-1]].to_pydatetime(),
        )
    ok = ~missing
    if ok.any():
        s.mean = float(vals[ok].mean())
        lo_i, hi_i = int(np.nanargmin(vals)), int(np.nanargmax(vals))
        s.low, s.low_at = float(vals[lo_i]), idx[lo_i].to_pydatetime()
        s.high, s.high_at = float(vals[hi_i]), idx[hi_i].to_pydatetime()
    both = ok & ~np.isnan(base)
    if both.any():
        s.base_mean = float(base[both].mean())
        mean_v = float(vals[both].mean())
        if abs(s.base_mean) > 1e-9:
            s.deviation_pct = (mean_v - s.base_mean) / abs(s.base_mean) * 100.0
    s.max_hist_days = int(a.n_hist[w].max()) if len(a.n_hist[w]) else 0
    size = max(1, math.ceil(s.n_steps / MAX_POINTS))
    s.bucket_steps = size
    s.series_start = idx[0].to_pydatetime()
    s.series = _bucket(vals, size)
    s.base_series = _bucket(base, size)
    run = a.run
    if run is not None:
        s.onset = _ts(a, run.first)
        s.direction = run.direction
        s.ongoing = a.ongoing
        s.before_window = a.before_window
        s.recovery = _ts(a, a.recovery) if a.recovery is not None else None
        s.worst_at = _ts(a, run.worst)
        s.worst_value = float(a.values[run.worst])
        s.worst_base = float(a.baseline[run.worst])
    return s


# --- rendering -------------------------------------------------------------------------------


def _vs(value: float | None, base: float | None) -> str:
    if value is None:
        return "no data"
    if base is None:
        return num(value)
    return f"{num(value)} vs baseline {num(base)}"


def _header(s: PairSummary) -> str:
    if s.n_steps == 0:
        return f"{s.entity} {s.metric}: no 15-min step inside the window."
    if s.mean is None:
        return (
            f"{s.entity} {s.metric}: NO DATA in all {s.n_steps} steps "
            "(cells down, or outside the data period)."
        )
    head = f"{s.entity} {s.metric}: mean {_vs(s.mean, s.base_mean)}"
    if s.deviation_pct is not None:
        head += f" ({pct(s.deviation_pct)})"
    assert s.low_at is not None and s.high_at is not None
    head += f"; min {num(s.low)} at {fmt(s.low_at)}, max {num(s.high)} at {fmt(s.high_at)}"
    if s.n_no_data:
        head += (
            f"; NO DATA (cells down) in {s.n_no_data}/{s.n_steps} steps, "
            f"{fmt(s.no_data_first)} to {fmt(s.no_data_last)}"
        )
    if s.base_mean is None:
        head += (
            f"; baseline unavailable (need {MIN_HISTORY_DAYS}+ earlier same-type days, "
            f"have {s.max_hist_days})"
        )
    return head + "."


def _deviation_line(s: PairSummary) -> str:
    if s.onset is None:
        if s.base_mean is None or s.n_steps == 0:
            return ""
        return "No sustained deviation from baseline in the steps that reported."
    where = " (already deviating before the window)" if s.before_window else ""
    line = (
        f"Deviation {s.direction} baseline: onset {fmt(s.onset)}{where}; worst "
        f"{num(s.worst_value)} vs {num(s.worst_base)} at {fmt(s.worst_at)}; "
    )
    if s.ongoing:
        return line + f"not recovered by the last step ({fmt(s.last_step)})."
    return line + f"recovery {fmt(s.recovery)}."


def _series_lines(s: PairSummary) -> list[str]:
    if not s.series or s.series_start is None:
        return []
    label = (
        f"{fmt_duration(timedelta(minutes=15 * s.bucket_steps))} buckets"
        if s.bucket_steps > 1
        else "15 min steps"
    )
    cells = " ".join("-" if v is None else num(v) for v in s.series)
    out = [f"series ({label} from {fmt(s.series_start)}): {cells}"]
    if any(v is not None for v in s.base_series):
        out.append("baseline: " + " ".join("-" if v is None else num(v) for v in s.base_series))
    return out


def _one_line(s: PairSummary) -> str:
    if s.n_steps == 0 or s.mean is None:
        return _header(s)
    dev = f" ({pct(s.deviation_pct)})" if s.deviation_pct is not None else ""
    base = f" vs {num(s.base_mean)}" if s.base_mean is not None else " (no baseline)"
    if s.onset is not None:
        tail = f"{s.direction} baseline from {fmt(s.onset)}, " + (
            "not recovered" if s.ongoing else f"recovered {fmt(s.recovery)}"
        )
    else:
        tail = "no deviation"
    return f"{s.entity} {s.metric}: mean {num(s.mean)}{base}{dev}; {tail}."


def render_pair(s: PairSummary, level: int) -> str:
    """Level 0: one short line. 1: summary and deviation. 2: plus series. 3: plus baseline."""
    if level == 0:
        return _one_line(s)
    lines = [_header(s)]
    dev = _deviation_line(s)
    if dev:
        lines.append(dev)
    if level >= 2:
        series = _series_lines(s)
        lines += series[:1] if level == 2 else series
    return "\n".join(lines)


def _day_kind(start: datetime) -> str:
    local = pd.DatetimeIndex([pd.Timestamp(start)]).tz_convert(LOCAL_TZ)
    return ["weekdays", "Saturdays", "Sundays"][int(day_type(local)[0])]


def _priority(s: PairSummary) -> tuple[Any, ...]:
    if s.onset is not None:
        return (0, s.onset)
    mag = abs(s.deviation_pct) if s.deviation_pct is not None else 0.0
    return (1, -mag)


def _pair_data(s: PairSummary) -> dict[str, Any]:
    return {
        "entity": s.entity,
        "metric": s.metric,
        "n_steps": s.n_steps,
        "n_no_data": s.n_no_data,
        "mean": s.mean,
        "min": s.low,
        "min_at": iso(s.low_at),
        "max": s.high,
        "max_at": iso(s.high_at),
        "baseline_mean": s.base_mean,
        "deviation_pct": s.deviation_pct,
        "onset": iso(s.onset),
        "recovery": iso(s.recovery),
        "direction": s.direction,
        "ongoing": s.ongoing,
        "series_start": iso(s.series_start),
        "series_step_minutes": s.bucket_steps * 15,
        "series": s.series,
        "baseline_series": s.base_series,
    }


# --- the tool --------------------------------------------------------------------------------


def query_kpis(ctx: ToolContext, args: QueryKpisArgs) -> ToolResult:
    try:
        window = make_window(args.start, args.end, ctx.asked_at)
    except TimeParseError as exc:
        return error_result("query_kpis", args, str(exc))

    metrics = list(dict.fromkeys(m.strip() for m in args.metrics))
    with ctx.engine.connect() as conn:
        idx = NodeIndex.load(conn)
        ids, notes, error = _resolve_entities(conn, idx, args)
        if error:
            return error_result("query_kpis", args, error)
        if args.entity_type == "core_node":
            available = _core_metric_names(conn, ids)
            valid = sorted({m for v in available.values() for m in v})
        else:
            valid = CELL_LEVEL_METRICS
        bad = [m for m in metrics if m not in valid]
        if bad:
            return error_result(
                "query_kpis",
                args,
                f"Unknown metric(s) {', '.join(bad)} for {args.entity_type}. "
                f"Valid: {', '.join(valid)}.",
            )
        head_notes = window.notes() + notes
        if window.empty:
            body = " ".join(head_notes)
            return ToolResult(
                tool="query_kpis",
                args=args.model_dump(),
                headline=body[:200],
                body=body,
                data={"pairs": []},
            )
        lead = window.start - LEAD_IN
        lo = (
            pd.Timestamp(lead).tz_convert(LOCAL_TZ).normalize() - pd.Timedelta(days=LOOKBACK_DAYS)
        ).tz_convert("UTC")
        local_days = pd.date_range(lead, window.end, freq="15min", tz="UTC").tz_convert(LOCAL_TZ)
        dows = isodow_values({int(t) for t in day_type(local_days)})
        if args.entity_type == "core_node":
            series = _fetch_core(conn, ids, metrics, lo.to_pydatetime(), lead, window.end, dows)
        else:
            series = _fetch_cell_level(
                conn, args.entity_type, ids, metrics, lo.to_pydatetime(), lead, window.end, dows
            )

    summaries: list[PairSummary] = []
    empty = pd.Series([], index=pd.DatetimeIndex([], tz="UTC"), dtype=float)
    for entity in ids:
        for metric in metrics:
            floors = _FLOORS.get(metric, Floors())
            if (entity, metric) not in series and args.entity_type == "core_node":
                notes.append(f"{entity} has no metric {metric}.")
                continue
            a = analyse(series.get((entity, metric), empty), window.start, window.end, floors)
            summaries.append(summarise(entity, metric, a))
    head_notes += [n for n in notes if n not in head_notes]
    return _result(args, window.start, window.end, window.asked_at, summaries, head_notes)


def _result(
    args: QueryKpisArgs,
    start: datetime,
    end: datetime,
    asked: datetime,
    summaries: list[PairSummary],
    notes: list[str],
) -> ToolResult:
    ranked = sorted(summaries, key=_priority)
    deviating = [s for s in ranked if s.onset is not None]
    with_base = [s for s in ranked if s.base_mean is not None]
    n = len(ranked)
    if deviating:
        first = deviating[0]
        lead = (
            f"Deviation in {len(deviating)} of {n} series. Earliest onset {fmt(first.onset)}: "
            f"{first.entity} {first.metric} {first.direction} baseline"
            + (" (began before the window)" if first.before_window else "")
            + "."
        )
    elif with_base:
        lead = f"No series deviates from its baseline between {fmt(start)} and {fmt(end)}."
    else:
        lead = (
            f"No baseline available for {fmt(start)} to {fmt(end)}: fewer than "
            f"{MIN_HISTORY_DAYS} earlier {_day_kind(start)} with data. Raw statistics only."
        )
    most = max((s.max_hist_days for s in with_base), default=0)
    thin = (
        f" Thin baseline: only {most} earlier {_day_kind(start)} with data; treat small "
        "deviations with caution."
        if with_base and most < THIN_HISTORY_DAYS
        else ""
    )
    base_note = (
        f"Baseline: median of the same time of day on earlier {_day_kind(start)} "
        f"(only data before {fmt(asked)}). Times are local step starts (15 min): an onset can "
        f"precede its cause by up to 15 min.{thin}"
    )
    head = [lead, base_note, *notes]
    head_text = "\n".join(head)

    chosen_level, shown = 0, ranked
    for level in (3, 2, 1, 0):
        total = len(head_text) + sum(len(render_pair(s, level)) + 1 for s in ranked)
        if total <= BODY_CHARS - 40:
            chosen_level = level
            break
    else:
        used = len(head_text) + 120
        shown = []
        for s in ranked:
            cost = len(render_pair(s, 0)) + 1
            if used + cost > BODY_CHARS - 40:
                break
            used += cost
            shown.append(s)
    truncated = len(shown) < n
    parts = [head_text, *(render_pair(s, chosen_level) for s in shown)]
    if truncated:
        parts.append(
            f"Omitted {n - len(shown)} of {n} series (budget); ask for fewer entities or metrics."
        )
    body = hard_cap("\n".join(parts))
    return ToolResult(
        tool="query_kpis",
        args=args.model_dump(),
        headline=lead[:200],
        body=body,
        data={
            "window": [iso(start), iso(end)],
            "baseline": "median of same time-of-day slots on earlier days of the same day type",
            "pairs": [_pair_data(s) for s in ranked],
        },
        truncated=truncated,
    )
