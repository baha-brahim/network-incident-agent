"""get_anomalies: the detector's alerts and anomalies, restated as they were known at `asked_at`.

The detector ran over the whole month, so a stored alert or anomaly that was still running at
`asked_at` carries numbers from the future (its end, its duration, its peak). Those are never
shown: an unfinished alert is described from the anomalies that had already started, and the
magnitude of an unfinished anomaly is recomputed from KPI data up to `asked_at`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from pydantic import Field
from sqlalchemy import Connection, text

from incident_agent.agent.tools.baseline import LEAD_IN, Floors, analyse, day_type, isodow_values
from incident_agent.agent.tools.common import (
    MAX_ROWS_CONSIDERED,
    Item,
    NodeIndex,
    assemble,
    error_result,
    join_ids,
    num,
    pct,
    trim,
)
from incident_agent.agent.tools.kpis import (
    _FLOORS,
    LOOKBACK_DAYS,
    _fetch_cell_level,
    _fetch_core,
)
from incident_agent.agent.tools.schema import ToolArgs
from incident_agent.agent.tools.timeutil import (
    LOCAL_TZ,
    STEP,
    TimeParseError,
    fmt,
    fmt_duration,
    iso,
    make_window,
)
from incident_agent.agent.types import EvidenceRef, ToolContext, ToolResult

MAX_ALERTS = 4
MAX_GROUPS = 3
MAX_RECOMPUTED = 8  # ongoing anomalies whose magnitude is rebuilt from KPIs, per call


class GetAnomaliesArgs(ToolArgs):
    start: str = Field(description="Window start, ISO 8601; no offset = Africa/Tunis local time.")
    end: str = Field(description="Window end, ISO 8601. Anything after the current time is cut.")
    region_id: str | None = Field(default=None, description="TUN, SAH, SFX or SUD.")
    entity_id: str | None = Field(
        default=None,
        description="A site, link, router or core node: alerts touching it or its relatives.",
    )


@dataclass
class _Anom:
    anomaly_id: str
    alert_id: str
    entity_type: str
    entity_id: str
    metric: str
    direction: str
    start_at: datetime
    end_at: datetime
    peak_z: float
    baseline_value: float
    observed_value: float
    ended: bool


def get_anomalies(ctx: ToolContext, args: GetAnomaliesArgs) -> ToolResult:
    try:
        window = make_window(args.start, args.end, ctx.asked_at)
    except TimeParseError as exc:
        return error_result("get_anomalies", args, str(exc))
    asked = window.asked_at

    with ctx.engine.connect() as conn:
        idx = NodeIndex.load(conn)
        region = args.region_id.strip().upper() if args.region_id else None
        if region is not None and region not in idx.regions:
            return error_result(
                "get_anomalies",
                args,
                f"Unknown region_id {region!r}. Regions: {', '.join(sorted(idx.regions))}.",
            )
        match: list[str] | None = None
        entity = args.entity_id.strip() if args.entity_id else None
        notes = window.notes()
        if entity:
            entity = idx.cells.get(entity.upper(), entity)
            if entity not in idx.nodes:
                entity = entity.upper()
            if entity in idx.regions:
                region = entity
            elif entity in idx.nodes:
                match = [entity, *idx.descendants(entity), *idx.ancestors(entity)]
            else:
                return error_result(
                    "get_anomalies",
                    args,
                    f"Unknown entity_id {args.entity_id!r}.{idx.suggest(args.entity_id or '')}",
                )
        if window.empty:
            body = " ".join(notes)
            return ToolResult(
                tool="get_anomalies",
                args=args.model_dump(),
                headline=body[:200],
                body=body,
                data={"alerts": []},
            )
        alerts, anoms = _load(conn, window.start, window.end, asked, region, match)
        if not alerts:
            scope = (
                f"{args.entity_id} or its relatives"
                if match
                else (f"region {region}" if region else "the network")
            )
            body = " ".join(
                [
                    f"No detector alerts for {scope} between {fmt(window.start)} and "
                    f"{fmt(window.end)}.",
                    *notes,
                ]
            )
            return ToolResult(
                tool="get_anomalies",
                args=args.model_dump(),
                headline=body[:200],
                body=body,
                data={"alerts": []},
            )
        items = _alert_items(conn, idx, alerts, anoms, asked, match, region)

    ongoing = [i for i in items if i.data["ongoing"]]
    head = [
        f"{len(items)} detector alert(s) overlap {fmt(window.start)} to {fmt(window.end)}"
        f"{f' ({len(ongoing)} still ongoing at asked_at {fmt(asked)})' if ongoing else ''}.",
        "Alerts still running are described only up to asked_at (end, final size and severity "
        "are not known yet).",
        *notes,
    ]
    ordered = sorted(items, key=lambda i: (not i.data["ongoing"], -i.data["score"]))
    ordered = ordered[:MAX_ROWS_CONSIDERED]
    out = assemble(
        head,
        ordered,
        omitted_line=lambda left: (
            f"Omitted {len(left)} other alert(s): "
            + "; ".join(f"{i.data['alert_id']} {i.data['severity']}" for i in left[:6])
        ),
    )
    refs = []
    for item in out.shown:
        refs += [item.ref] if item.ref else []
        refs += [EvidenceRef(**r) for r in item.data["anomaly_refs"]]
    return ToolResult(
        tool="get_anomalies",
        args=args.model_dump(),
        headline=head[0][:200],
        body=out.body,
        refs=refs,
        data={
            "window": [iso(window.start), iso(window.end)],
            "alerts": [{k: v for k, v in i.data.items() if k != "anomaly_refs"} for i in out.shown],
        },
        truncated=out.truncated,
    )


def _load(
    conn: Connection,
    start: datetime,
    end: datetime,
    asked: datetime,
    region: str | None,
    match: list[str] | None,
) -> tuple[list[Any], list[_Anom]]:
    sql = [
        "SELECT alert_id, start_at, end_at, region_ids, entity_ids, metrics, severity, score, "
        "n_anomalies, summary FROM alerts WHERE start_at <= :end AND end_at >= :start"
    ]
    params: dict[str, Any] = {"start": start, "end": end}
    if region:
        sql.append("AND (cardinality(region_ids) = 0 OR :region = ANY(region_ids))")
        params["region"] = region
    if match:
        sql.append("AND entity_ids && CAST(:match AS text[])")
        params["match"] = match
    sql.append("ORDER BY start_at, alert_id")
    alerts = list(conn.execute(text(" ".join(sql)), params).all())
    if not alerts:
        return [], []
    rows = conn.execute(
        text(
            "SELECT anomaly_id, alert_id, entity_type, entity_id, metric, direction, start_at, "
            "end_at, peak_z, baseline_value, observed_value FROM anomalies "
            "WHERE alert_id = ANY(:ids) AND start_at <= :asked ORDER BY start_at, anomaly_id"
        ),
        {"ids": [a.alert_id for a in alerts], "asked": asked},
    ).all()
    anoms = [
        _Anom(
            r.anomaly_id, r.alert_id, r.entity_type, r.entity_id, r.metric, r.direction,
            r.start_at.astimezone(UTC), r.end_at.astimezone(UTC), r.peak_z, r.baseline_value,
            r.observed_value,
            ended=r.end_at + STEP <= asked,
        )
        for r in rows
    ]  # fmt: skip
    return alerts, anoms


def _entities_text(visible: list[_Anom]) -> str:
    sites = sorted({a.entity_id for a in visible if a.entity_type == "site"})
    core = sorted({a.entity_id for a in visible if a.entity_type == "core_node"})
    regions = sorted({a.entity_id for a in visible if a.entity_type == "region"})
    parts: list[str] = []
    if sites:
        parts.append(f"{len(sites)} site(s) ({join_ids(sites, 4)})")
    if core:
        parts.append("core " + join_ids(core, 3))
    if regions:
        parts.append("region-level " + join_ids(regions, 4))
    return "; ".join(parts) or "-"


def _alert_items(
    conn: Connection,
    idx: NodeIndex,
    alerts: list[Any],
    anoms: list[_Anom],
    asked: datetime,
    match: list[str] | None,
    region: str | None,
) -> list[Item]:
    by_alert: dict[str, list[_Anom]] = {}
    for a in anoms:
        by_alert.setdefault(a.alert_id, []).append(a)
    budget = [MAX_RECOMPUTED]
    items: list[Item] = []
    for al in alerts:
        visible = by_alert.get(al.alert_id, [])
        if not visible:
            continue
        ended = al.end_at + STEP <= asked
        shown = visible
        if match:
            shown = [a for a in visible if a.entity_id in match] or visible
        elif region:
            shown = [a for a in visible if idx.nodes.get(a.entity_id) is None
                     or idx.nodes[a.entity_id].region_id in (None, region)
                     or a.entity_id == region] or visible  # fmt: skip
        groups: dict[tuple[str, str], list[_Anom]] = {}
        for a in shown:
            groups.setdefault((a.metric, a.direction), []).append(a)
        ranked = sorted(groups.items(), key=lambda kv: (-len({a.entity_id for a in kv[1]}), kv[0]))
        group_lines: list[str] = []
        anomaly_refs: list[dict[str, str]] = []
        for (metric, direction), members in ranked[:MAX_GROUPS]:
            line, ref = _group_line(conn, idx, metric, direction, members, asked, budget)
            group_lines.append(line)
            if ref:
                anomaly_refs.append(ref)
        if len(ranked) > MAX_GROUPS:
            rest = ", ".join(f"{m} {d}" for (m, d), _ in ranked[MAX_GROUPS:])
            group_lines.append(
                f"  +{len(ranked) - MAX_GROUPS} more metric group(s): {trim(rest, 90)}"
            )

        if ended:
            span = (
                f"{fmt(al.start_at)} to {fmt(al.end_at)} ({fmt_duration(al.end_at - al.start_at)})"
            )
            head = f"{al.alert_id} {al.severity} ended, {span}: {trim(al.summary, 230)}"
        else:
            head = (
                f"{al.alert_id} ONGOING since {fmt(al.start_at)} "
                f"({fmt_duration(asked - al.start_at)} so far); {len(visible)} anomalies so far on "
                f"{_entities_text(visible)}; severity not final"
            )
        summary = trim(
            f"{'ended' if ended else 'ongoing'} alert from {fmt(al.start_at)}: "
            f"{_entities_text(visible)}; metrics: {', '.join(sorted({a.metric for a in visible}))}",
            170,
        )
        items.append(
            Item(
                line="\n".join([head, *group_lines]),
                sort=(al.start_at, al.alert_id),
                ref=EvidenceRef(ref=al.alert_id, kind="alert", summary=summary),
                data={
                    "alert_id": al.alert_id,
                    "start_at": iso(al.start_at),
                    "end_at": iso(al.end_at) if ended else None,
                    "ongoing": not ended,
                    "severity": al.severity if ended else None,
                    "score": float(al.score) if ended else 99.0,
                    "n_visible_anomalies": len(visible),
                    "entities": sorted({a.entity_id for a in visible}),
                    "metrics": sorted({a.metric for a in visible}),
                    "anomaly_refs": anomaly_refs,
                },
            )
        )
    return items


def _group_line(
    conn: Connection,
    idx: NodeIndex,
    metric: str,
    direction: str,
    members: list[_Anom],
    asked: datetime,
    budget: list[int],
) -> tuple[str, dict[str, str] | None]:
    entities = {a.entity_id for a in members}
    finished = [a for a in members if a.ended]
    live = [a for a in members if not a.ended]
    prefix = (
        f"  {metric} {direction} on {len(entities)} entit{'y' if len(entities) == 1 else 'ies'}"
    )
    if live:
        rep = min(live, key=lambda a: (a.start_at, a.entity_id))
        now = _so_far(conn, idx, rep, asked) if budget[0] > 0 else None
        budget[0] -= 1
        if now is None:
            text_ = f"{prefix}: ongoing, e.g. {rep.entity_id} since {fmt(rep.start_at)}"
        else:
            value, base = now
            dev = f" ({pct((value - base) / abs(base) * 100)})" if abs(base) > 1e-9 else ""
            text_ = (
                f"{prefix}: ongoing, e.g. {rep.entity_id} since {fmt(rep.start_at)}, "
                f"so far {num(value)} vs baseline {num(base)}{dev}"
            )
        ref = EvidenceRef(
            ref=rep.anomaly_id,
            kind="anomaly",
            summary=trim(
                f"{rep.entity_id} {metric} {direction}, ongoing since {fmt(rep.start_at)}", 150
            ),
        )
        return text_, ref.model_dump()
    rep = max(finished, key=lambda a: abs(a.peak_z))
    text_ = (
        f"{prefix}: worst {rep.entity_id} z {rep.peak_z:.1f}, {num(rep.baseline_value)} -> "
        f"{num(rep.observed_value)}, {fmt(rep.start_at)} to {fmt(rep.end_at)}"
    )
    ref = EvidenceRef(
        ref=rep.anomaly_id,
        kind="anomaly",
        summary=trim(
            f"{rep.entity_id} {metric} {direction}, z {rep.peak_z:.1f}, baseline "
            f"{num(rep.baseline_value)} -> {num(rep.observed_value)}",
            150,
        ),
    )
    return text_, ref.model_dump()


def _so_far(
    conn: Connection, idx: NodeIndex, a: _Anom, asked: datetime
) -> tuple[float, float] | None:
    """Worst value up to `asked` for an anomaly that is still running, with its baseline."""
    if a.entity_type == "core_node":
        kind = "core_node"
    elif a.entity_type in ("site", "region"):
        kind = a.entity_type
    else:
        return None
    lead = a.start_at - LEAD_IN
    lo = (
        pd.Timestamp(lead).tz_convert(LOCAL_TZ).normalize() - pd.Timedelta(days=LOOKBACK_DAYS)
    ).tz_convert("UTC")
    days = pd.date_range(lead, asked, freq="15min", tz="UTC").tz_convert(LOCAL_TZ)
    dows = isodow_values({int(t) for t in day_type(days)})
    try:
        if kind == "core_node":
            series = _fetch_core(
                conn, [a.entity_id], [a.metric], lo.to_pydatetime(), lead, asked, dows
            )
        else:
            series = _fetch_cell_level(
                conn, kind, [a.entity_id], [a.metric], lo.to_pydatetime(), lead, asked, dows
            )
    except Exception:  # unknown metric name for this level: fall back to the bare description
        return None
    s = series.get((a.entity_id, a.metric))
    if s is None or s.empty:
        return None
    an = analyse(s, a.start_at, asked, _FLOORS.get(a.metric, Floors()))
    w = an.in_window & ~pd.isna(an.values)
    if not w.any():
        return None
    vals = an.values.copy()
    vals[~w] = float("nan")
    pos = int(np.nanargmin(vals) if a.direction == "drop" else np.nanargmax(vals))
    base = an.baseline[pos]
    if pd.isna(base):
        return None
    return float(vals[pos]), float(base)
