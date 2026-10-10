"""Sanity-check plots: one PNG per scenario and one weekly overview per region."""

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import matplotlib.dates as mdates
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from incident_agent.simulator.world import World

TZ = ZoneInfo("Africa/Tunis")
CONTEXT = pd.Timedelta(days=1)
MAX_LINES = 6  # more affected sites than this are collapsed into one aggregate line
NATIONWIDE_KINDS = {"dns_degradation", "public_holiday"}
MAX_LABELS = 12  # label clusters per plot (every evidence marker still gets a line)

# (column, y label, aggregation) for the per-scenario small multiples.
# "wmean" is the DL-volume-weighted mean over the cells that reported (NaN while a cell is down).
CELL_PANELS = [
    ("dl_volume_mb", "DL volume (MB)", "sum"),
    ("availability_pct", "availability (%)", "mean"),
    ("rrc_success_pct", "RRC success (%)", "wmean"),
    ("latency_ms", "latency (ms)", "wmean"),
    ("drop_rate_pct", "drop rate (%)", "wmean"),
    ("prb_util_pct", "PRB util (%)", "mean"),
]
DNS_PANELS = [("query_success_pct", "DNS success (%)"), ("resolution_ms", "DNS resolution (ms)")]

# Where an evidence row's timestamp lives, and a short label for it.
EVIDENCE_TIME = {
    "alarms": ("raised_at", "alarm_type", "alarm_id"),
    "changes": ("executed_at", "change_type", "change_id"),
    "maintenance": ("start_at", None, "mw_id"),
    "external_events": ("start_at", "event_type", "event_id"),
}
EVIDENCE_COLORS = {
    "alarms": "tab:red",
    "changes": "tab:purple",
    "maintenance": "tab:green",
    "external_events": "tab:orange",
}


def make_plots(world: World, out_dir: Path) -> list[Path]:
    """Write all PNGs into out_dir and return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [_scenario_plot(world, row, out_dir) for row in world.scenarios.itertuples(index=False)]
    paths += [
        _region_overview(world, str(region_id), out_dir) for region_id in world.regions["region_id"]
    ]
    return paths


# ---------------------------------------------------------------- scope resolution


def _downstream_sites(nodes: pd.DataFrame, node_id: str) -> list[str]:
    """The node itself if it is a site, otherwise every site below it in the parent tree."""
    children: dict[str, list[str]] = defaultdict(list)
    for child, parent in zip(nodes["node_id"], nodes["parent_id"], strict=True):
        if isinstance(parent, str):
            children[parent].append(str(child))
    site_ids = set(nodes.loc[nodes["node_type"] == "site", "node_id"])
    found: list[str] = []
    stack = [node_id]
    while stack:
        current = stack.pop()
        if current in site_ids:
            found.append(current)
        else:
            stack.extend(children[current])
    return sorted(found)


def _resolve_groups(world: World, scenario: pd.Series) -> dict[str, list[str]]:
    """Label -> cell ids to plot as one line each."""
    cells, nodes = world.cells, world.nodes
    cells_of_site = cells.groupby("site_id")["cell_id"].apply(list).to_dict()
    cell_ids = set(cells["cell_id"])
    site_of_region = nodes[nodes["node_type"] == "site"].groupby("region_id")["node_id"].apply(list)

    affected: Sequence[str] = list(scenario["affected_node_ids"])
    if affected and scenario["kind"] not in NATIONWIDE_KINDS:
        named_cells = [n for n in affected if n in cell_ids]
        if len(named_cells) == len(affected):
            if len(named_cells) <= MAX_LINES:
                return {c: [c] for c in named_cells}
            return {f"{len(named_cells)} affected cells": named_cells}
        sites: set[str] = set()
        for node_id in affected:
            if node_id in cell_ids:
                sites.add(str(cells.loc[cells["cell_id"] == node_id, "site_id"].iloc[0]))
            else:
                sites.update(_downstream_sites(nodes, node_id))
        by_site = {s: cells_of_site[s] for s in sorted(sites) if s in cells_of_site}
        if 0 < len(by_site) <= MAX_LINES:
            return by_site
        if by_site:
            return {f"{len(by_site)} affected sites": [c for v in by_site.values() for c in v]}

    # Nationwide or unscoped: one aggregate line per region.
    region_ids = list(scenario["affected_region_ids"]) or list(world.regions["region_id"])
    groups: dict[str, list[str]] = {}
    for region_id in region_ids:
        sites_in_region = site_of_region.get(region_id, [])
        region_cells = [c for s in sites_in_region for c in cells_of_site.get(s, [])]
        if region_cells:
            groups[str(region_id)] = region_cells
    return groups


# ---------------------------------------------------------------- shared drawing helpers


def _local(ts: pd.Series) -> pd.Series:
    local: pd.Series = ts.dt.tz_convert(TZ)
    return local


def _x(when: pd.Timestamp) -> float:
    """Matplotlib date number (days since 1970-01-01, the default epoch)."""
    return when.timestamp() / 86400


def _format_time_axis(axes: Sequence[Axes], span: pd.Timedelta) -> None:
    locator = mdates.AutoDateLocator(tz=TZ, minticks=4, maxticks=10)  # type: ignore[no-untyped-call]
    fmt = "%d/%m %H:%M" if span <= pd.Timedelta(days=4) else "%a %d/%m"
    axes[-1].xaxis.set_major_locator(locator)
    formatter = mdates.DateFormatter(fmt, tz=TZ)  # type: ignore[no-untyped-call]
    axes[-1].xaxis.set_major_formatter(formatter)
    axes[-1].set_xlabel("local time (Africa/Tunis)")
    for ax in axes:
        ax.grid(alpha=0.25)
        ax.tick_params(labelsize=8)


def _aggregate(
    kpis: pd.DataFrame, cell_to_label: dict[str, str], column: str, how: str
) -> pd.DataFrame:
    sub = kpis[["ts", "cell_id", column]].copy()
    sub["label"] = sub["cell_id"].map(cell_to_label)
    if how != "wmean":
        out = sub.groupby(["label", "ts"])[column].agg(how).reset_index()
        return out
    weight = kpis["dl_volume_mb"].where(sub[column].notna(), 0.0)
    sub["w"] = weight
    sub["wx"] = sub[column].fillna(0.0) * weight
    grouped = sub.groupby(["label", "ts"])
    agg = grouped.agg(wx=("wx", "sum"), w=("w", "sum"), plain=(column, "mean")).reset_index()
    # Zero traffic but cells reporting: plain mean; every cell down: NaN (the line breaks).
    agg[column] = (agg["wx"] / agg["w"].where(agg["w"] > 0)).fillna(agg["plain"])
    return agg[["label", "ts", column]]


def _evidence_points(world: World, evidence: object) -> list[tuple[pd.Timestamp, str, str]]:
    """(time, table, short label) for every evidence item that resolves to a row."""
    points: list[tuple[pd.Timestamp, str, str]] = []
    if not isinstance(evidence, list):
        return points
    for item in evidence:
        table, ident = item.get("table"), item.get("id")
        if table not in EVIDENCE_TIME:
            continue
        time_col, label_col, id_col = EVIDENCE_TIME[table]
        df = getattr(world, table)
        row = df[df[id_col] == ident]
        if row.empty:
            continue
        label = str(row.iloc[0][label_col]) if label_col else "maintenance"
        points.append((pd.Timestamp(row.iloc[0][time_col]), table, label))
    return sorted(points)


def _decoy_points(world: World, confounders: object) -> list[tuple[pd.Timestamp, str]]:
    """(time, 'decoy: <alarm type / change type>') for each labelled confounder."""
    decoys = _evidence_points(world, confounders)
    return [(when, f"decoy: {label}") for when, _table, label in decoys]


def _label_clusters(
    points: list[tuple[pd.Timestamp, str, str]],
) -> list[tuple[pd.Timestamp, str, str]]:
    """Merge markers less than 30 minutes apart so their labels do not overprint."""
    clusters: list[list[tuple[pd.Timestamp, str, str]]] = []
    for point in points:
        if clusters and point[0] - clusters[-1][-1][0] < pd.Timedelta(minutes=30):
            clusters[-1].append(point)
        else:
            clusters.append([point])
    out = []
    for cluster in clusters:
        names = list(dict.fromkeys(label for _, _, label in cluster))
        extra = [f"+{len(names) - 3}"] if len(names) > 3 else []
        text = "\n".join(names[:3] + extra)
        out.append((cluster[0][0], cluster[0][1], text))
    return out


# ---------------------------------------------------------------- per-scenario plot


def _scenario_plot(world: World, scenario_row: object, out_dir: Path) -> Path:
    scenario = pd.Series(scenario_row._asdict())  # type: ignore[attr-defined]
    scenario_id = str(scenario["scenario_id"])
    start_at = pd.Timestamp(scenario["start_at"])
    impact_start = pd.Timestamp(scenario["impact_start_at"])
    end_at = pd.Timestamp(scenario["end_at"])
    lo = min(start_at, impact_start) - CONTEXT
    hi = end_at + CONTEXT

    groups = _resolve_groups(world, scenario)
    cell_to_label = {cell: label for label, cells in groups.items() for cell in cells}
    kpis = world.cell_kpis
    window = kpis[(kpis["ts"] >= lo) & (kpis["ts"] <= hi) & kpis["cell_id"].isin(cell_to_label)]

    show_dns = scenario["kind"] == "dns_degradation" or str(
        scenario["root_cause_node_id"]
    ).startswith("CORE-DNS")
    n_panels = len(CELL_PANELS) + (len(DNS_PANELS) if show_dns else 0)
    fig = Figure(figsize=(12, 1.7 * n_panels + 1.2), layout="constrained")
    FigureCanvasAgg(fig)
    axes = list(fig.subplots(n_panels, 1, sharex=True))

    for ax, (column, ylabel, how) in zip(axes, CELL_PANELS, strict=False):
        agg = _aggregate(window, cell_to_label, column, how)
        for label, part in agg.groupby("label"):
            ax.plot(_local(part["ts"]), part[column], lw=1.1, label=str(label))
        ax.set_ylabel(ylabel, fontsize=8)
    if show_dns:
        core = world.core_kpis
        dns = core[
            core["node_id"].str.startswith("CORE-DNS") & (core["ts"] >= lo) & (core["ts"] <= hi)
        ]
        for ax, (metric, ylabel) in zip(axes[len(CELL_PANELS) :], DNS_PANELS, strict=True):
            part = dns[dns["metric"] == metric]
            ax.plot(_local(part["ts"]), part["value"], lw=1.1, color="tab:blue")
            ax.set_ylabel(ylabel, fontsize=8)

    _decorate_scenario(world, fig, axes, scenario, (lo, hi), (start_at, impact_start, end_at))
    path = out_dir / f"{scenario_id}.png"
    fig.savefig(path, dpi=110)
    return path


def _decorate_scenario(
    world: World,
    fig: Figure,
    axes: list[Axes],
    scenario: pd.Series,
    window: tuple[pd.Timestamp, pd.Timestamp],
    times: tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp],
) -> None:
    start_at, impact_start, end_at = times
    points = _evidence_points(world, scenario["evidence"])
    decoys = _decoy_points(world, scenario["confounders"])
    for i, ax in enumerate(axes):
        ax.axvspan(
            _x(impact_start),
            _x(end_at),
            color="tab:red",
            alpha=0.12,
            label="impact window" if i == 0 else None,
        )
        if start_at < impact_start:
            ax.axvline(
                _x(start_at),
                color="black",
                ls="--",
                lw=1,
                label="root cause start" if i == 0 else None,
            )
        for when, table, _ in points:
            ax.axvline(_x(when), color=EVIDENCE_COLORS[table], alpha=0.5, lw=0.8)
        for when, _ in decoys:
            ax.axvline(
                _x(when),
                color="grey",
                ls=":",
                lw=1.3,
                label="decoy (confounder)" if i == 0 and when == decoys[0][0] else None,
            )
    top = axes[0]
    for when, table, text in _label_clusters(points)[:MAX_LABELS]:
        top.annotate(
            text,
            (_x(when), 1.0),
            xycoords=("data", "axes fraction"),
            rotation=90,
            fontsize=6,
            color=EVIDENCE_COLORS[table],
            ha="right",
            va="bottom",
        )
    for when, text in decoys:
        top.annotate(
            text,
            (_x(when), 0.97),
            xycoords=("data", "axes fraction"),
            rotation=90,
            fontsize=6,
            color="dimgrey",
            ha="right",
            va="top",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.7, "pad": 0.5},
        )
    handles, labels = top.get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, fontsize=8, loc="outside lower center", ncols=6)
    _format_time_axis(axes, window[1] - window[0])
    fig.suptitle(
        f"{scenario['scenario_id']}  |  {scenario['kind']}  |  difficulty: {scenario['difficulty']}"
        f"  |  is_incident: {bool(scenario['is_incident'])}",
        fontsize=11,
    )


# ---------------------------------------------------------------- region overview


def _region_overview(world: World, region_id: str, out_dir: Path) -> Path:
    nodes, cells, kpis = world.nodes, world.cells, world.cell_kpis
    sites = nodes.loc[(nodes["node_type"] == "site") & (nodes["region_id"] == region_id), "node_id"]
    region_cells = cells.loc[cells["site_id"].isin(sites), "cell_id"]
    data = kpis[kpis["cell_id"].isin(region_cells)]
    hi = data["ts"].max() if len(data) else kpis["ts"].max()
    lo = hi - pd.Timedelta(days=7)
    data = data[data["ts"] > lo]

    by_ts = data.groupby("ts")
    volume = by_ts["dl_volume_mb"].sum()
    avail_mean = by_ts["availability_pct"].mean()
    avail_min = by_ts["availability_pct"].min()
    label = dict.fromkeys(data["cell_id"].unique(), region_id)
    weighted = {
        col: _aggregate(data, label, col, "wmean").set_index("ts")[col]
        for col in ("rrc_success_pct", "latency_ms")
    }

    fig = Figure(figsize=(12, 8), layout="constrained")
    FigureCanvasAgg(fig)
    ax_vol, ax_av, ax_rrc, ax_lat = fig.subplots(4, 1, sharex=True)
    ax_vol.plot(volume.index.tz_convert(TZ), volume.to_numpy(), lw=1.1)
    ax_vol.set_ylabel("DL volume (MB)", fontsize=8)
    ax_av.plot(avail_mean.index.tz_convert(TZ), avail_mean.to_numpy(), lw=1.1, label="mean")
    ax_av.plot(avail_min.index.tz_convert(TZ), avail_min.to_numpy(), lw=0.8, label="min")
    ax_av.set_ylabel("availability (%)", fontsize=8)
    ax_av.legend(fontsize=7, loc="center right")
    for ax, col, ylabel in (
        (ax_rrc, "rrc_success_pct", "RRC success (%, vol-weighted)"),
        (ax_lat, "latency_ms", "latency (ms, vol-weighted)"),
    ):
        ax.plot(
            pd.DatetimeIndex(weighted[col].index).tz_convert(TZ), weighted[col].to_numpy(), lw=1.1
        )
        ax.set_ylabel(ylabel, fontsize=8)

    sc = world.scenarios
    for row in sc.itertuples(index=False):
        regions = [str(r) for r in cast("Sequence[str]", row.affected_region_ids)]
        if region_id not in regions and regions:
            continue
        s, e = pd.Timestamp(str(row.impact_start_at)), pd.Timestamp(str(row.end_at))
        if e < lo or s > hi:
            continue
        for ax in (ax_vol, ax_av, ax_rrc, ax_lat):
            color = "tab:red" if row.is_incident else "tab:gray"
            ax.axvspan(_x(s), _x(e), color=color, alpha=0.12)

    _format_time_axis([ax_vol, ax_av, ax_rrc, ax_lat], hi - lo)
    name = world.regions.loc[world.regions["region_id"] == region_id, "name"].iloc[0]
    fig.suptitle(f"{region_id} ({name})  |  last 7 days  |  red = incident, grey = red herring")
    path = out_dir / f"overview_{region_id}.png"
    fig.savefig(path, dpi=110)
    return path
