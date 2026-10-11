"""KPI series for charts: the query and the baseline of the `query_kpis` tool, downsampled.

Same rules as the tool: nothing after `now` is visible, and the baseline of a step uses only
earlier days. `now` is the investigation's time inside a run, and the dataset's own now when a
visitor browses.
"""

import math
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import Engine

from incident_agent.agent.tools.baseline import (
    LEAD_IN,
    Analysis,
    Floors,
    analyse,
    day_type,
    isodow_values,
)
from incident_agent.agent.tools.common import NodeIndex
from incident_agent.agent.tools.kpis import (
    _FLOORS,
    CELL_LEVEL_METRICS,
    LOOKBACK_DAYS,
    QueryKpisArgs,
    _bucket,
    _core_metric_names,
    _fetch_cell_level,
    _fetch_core,
    _resolve_entities,
)
from incident_agent.agent.tools.timeutil import LOCAL_TZ, TimeParseError, fmt, make_window
from incident_agent.agent.types import ToolContext, ToolResult
from incident_agent.api.schemas import KpiDeviation, KpiSeries

MAX_SPAN = timedelta(days=7)
MAX_POINTS = 200
CHART_POINTS = 96
CHART_PAIRS = 6


class KpiInputError(Exception):
    """The request names something that does not exist or cannot be shown."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def unit_of(metric: str) -> str:
    for suffix, unit in (("_pct", "%"), ("_ms", "ms"), ("_mb", "MB")):
        if metric.endswith(suffix):
            return unit
    return {"active_users": "users", "cells_down": "cells"}.get(metric, "")


def _round(values: list[float | None]) -> list[float | None]:
    return [None if v is None else round(v, 3) for v in values]


def _series(
    args: QueryKpisArgs, entity: str, metric: str, a: Analysis, window_start: datetime,
    window_end: datetime, clamped: bool, notes: list[str], max_points: int,
) -> KpiSeries:  # fmt: skip
    inside = a.in_window
    index, values, base = a.index[inside], a.values[inside], a.baseline[inside]
    size = max(1, math.ceil(len(values) / max_points))
    deviation = None
    if a.run is not None:
        deviation = KpiDeviation(
            direction="below" if a.run.direction == "below" else "above",
            onset=a.index[a.run.first].to_pydatetime(),
            recovery=a.index[a.recovery].to_pydatetime() if a.recovery is not None else None,
            ongoing=a.ongoing,
            began_before_window=a.before_window,
        )
    return KpiSeries(
        entity_type=args.entity_type,
        entity_id=entity,
        metric=metric,
        unit=unit_of(metric),
        start=index[0].to_pydatetime() if len(index) else window_start,
        end=window_end,
        step_minutes=15 * size,
        values=_round(_bucket(values, size)),
        baseline=_round(_bucket(base, size)),
        baseline_available=bool((~np.isnan(base)).any()),
        deviation=deviation,
        clamped_to_now=clamped,
        note=" ".join(notes) or None,
    )


def kpi_series(
    engine: Engine,
    *,
    entity_type: str,
    entity_ids: list[str],
    metrics: list[str],
    start: str,
    end: str,
    now: datetime,
    max_points: int = MAX_POINTS,
) -> dict[tuple[str, str], KpiSeries]:
    """One series per (entity, metric). Raises `KpiInputError` if the request cannot be shown."""
    try:
        args = QueryKpisArgs.model_validate(
            {
                "entity_type": entity_type,
                "entity_ids": entity_ids,
                "metrics": metrics,
                "start": start,
                "end": end,
            }
        )
        window = make_window(start, end, now)
    except (ValueError, TimeParseError) as exc:
        raise KpiInputError(str(exc)) from exc
    if window.empty:
        raise KpiInputError("The window starts after the dataset's now; nothing is visible there.")
    if window.end - window.start > MAX_SPAN:
        raise KpiInputError("The window is longer than 7 days.")

    with engine.connect() as conn:
        idx = NodeIndex.load(conn)
        ids, notes, error = _resolve_entities(conn, idx, args)
        if error:
            raise KpiInputError(error, status=404)
        valid = (
            sorted({m for v in _core_metric_names(conn, ids).values() for m in v})
            if entity_type == "core_node"
            else CELL_LEVEL_METRICS
        )
        bad = [m for m in args.metrics if m not in valid]
        if bad:
            raise KpiInputError(
                f"Unknown metric(s) {', '.join(bad)} for {entity_type}. Valid: {', '.join(valid)}."
            )
        lead = window.start - LEAD_IN
        lo = (
            pd.Timestamp(lead).tz_convert(LOCAL_TZ).normalize() - pd.Timedelta(days=LOOKBACK_DAYS)
        ).tz_convert("UTC")
        steps = pd.date_range(lead, window.end, freq="15min", tz="UTC").tz_convert(LOCAL_TZ)
        dows = isodow_values({int(t) for t in day_type(steps)})
        if entity_type == "core_node":
            series = _fetch_core(
                conn, ids, args.metrics, lo.to_pydatetime(), lead, window.end, dows
            )
        else:
            series = _fetch_cell_level(
                conn, entity_type, ids, args.metrics, lo.to_pydatetime(), lead, window.end, dows
            )

    empty = pd.Series([], index=pd.DatetimeIndex([], tz="UTC"), dtype=float)
    out: dict[tuple[str, str], KpiSeries] = {}
    cut = [f"Cut at the dataset's now ({fmt(window.asked_at)}, Africa/Tunis)."]
    all_notes = (cut if window.clamped else []) + notes
    for entity in ids:
        for metric in args.metrics:
            if entity_type == "core_node" and (entity, metric) not in series:
                continue
            analysis = analyse(
                series.get((entity, metric), empty),
                window.start,
                window.end,
                _FLOORS.get(metric, Floors()),
            )
            out[(entity, metric)] = _series(
                args, entity, metric, analysis, window.start, window.end, window.clamped,
                all_notes, max_points,
            )  # fmt: skip
    return out


def charts_for(ctx: ToolContext, result: ToolResult) -> list[dict[str, Any]] | None:
    """Finer series for the pairs a `query_kpis` call returned, to draw its chart."""
    pairs = (result.data or {}).get("pairs") or []
    if not pairs:
        return None
    wanted = [(p["entity"], p["metric"]) for p in pairs[:CHART_PAIRS]]
    args = result.args
    national = args["entity_type"] == "national"
    series = kpi_series(
        ctx.engine,
        entity_type=args["entity_type"],
        entity_ids=[] if national else list(dict.fromkeys(e for e, _ in wanted)),
        metrics=list(dict.fromkeys(m for _, m in wanted)),
        start=args["start"],
        end=args["end"],
        now=ctx.asked_at,
        max_points=CHART_POINTS,
    )  # fmt: skip
    return [series[key].model_dump(mode="json") for key in wanted if key in series]
