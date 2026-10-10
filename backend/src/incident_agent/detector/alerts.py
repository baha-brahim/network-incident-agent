"""Group anomalies into alerts, score them and write one-sentence summaries.

Grouping rules, in order (anomalies that end up connected form one alert):

1. Site anomalies join when they share an aggregation router (so also a link or a site) and
   overlap in time.
2. A region-level anomaly joins the site group of its region that it overlaps most. If there is
   none, region-level anomalies of the same region that overlap in time form their own group.
3. Core anomalies that overlap in time are merged. If one involves DNS or the AMF (which every
   site depends on) the group pulls in every group that overlaps it: a nationwide alert.
4. Groups from `nationwide_min_regions` or more regions active at the same moment are merged
   (a nationwide effect with no core signal). Two regions at the same time stay apart.
5. UPF-only core groups join the overlapping group in a region that the UPF serves, or stand
   alone.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from incident_agent.detector.anomalies import Anomaly
from incident_agent.detector.config import DetectorConfig
from incident_agent.detector.series import Topology

ALERT_COLUMNS = [
    "alert_id",
    "start_at",
    "end_at",
    "region_ids",
    "entity_ids",
    "metrics",
    "severity",
    "score",
    "n_anomalies",
    "summary",
    "status",
]
ANOMALY_COLUMNS = [
    "anomaly_id",
    "alert_id",
    "entity_type",
    "entity_id",
    "region_id",
    "metric",
    "direction",
    "start_at",
    "end_at",
    "n_steps",
    "peak_z",
    "baseline_value",
    "observed_value",
]


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)  # lowest index wins: deterministic


@dataclass(frozen=True)
class _Unit:
    members: tuple[int, ...]
    start: int
    end: int
    regions: frozenset[str]


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int, gap: int) -> bool:
    return a_start <= b_end + gap and b_start <= a_end + gap


def _overlap_steps(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start) + 1)


def _chain(indices: list[int], anoms: list[Anomaly], gap: int) -> list[list[int]]:
    """Split anomalies into time-connected chains (overlapping within `gap` steps)."""
    chains: list[list[int]] = []
    end = -(10**9)
    for i in sorted(indices, key=lambda k: (anoms[k].start, k)):
        a = anoms[i]
        if chains and a.start <= end + gap:
            chains[-1].append(i)
            end = max(end, a.end)
        else:
            chains.append([i])
            end = a.end
    return chains


def _units(uf: _UnionFind, anoms: list[Anomaly], subset: list[int]) -> list[_Unit]:
    groups: dict[int, list[int]] = {}
    for i in subset:
        groups.setdefault(uf.find(i), []).append(i)
    out = []
    for members in groups.values():
        members.sort()
        out.append(
            _Unit(
                tuple(members),
                min(anoms[i].start for i in members),
                max(anoms[i].end for i in members),
                frozenset(r for i in members if (r := anoms[i].region_id) is not None),
            )
        )
    out.sort(key=lambda u: (u.start, u.members[0]))
    return out


def group_anomalies(anoms: list[Anomaly], topo: Topology, cfg: DetectorConfig) -> list[list[int]]:
    """Indices of anomalies, grouped by alert. Each group is sorted; groups are ordered by start."""
    gap = cfg.merge_gap_steps
    uf = _UnionFind(len(anoms))
    site = [i for i, a in enumerate(anoms) if a.entity_type == "site"]
    region = [i for i, a in enumerate(anoms) if a.entity_type == "region"]
    core = [i for i, a in enumerate(anoms) if a.entity_type == "core_node"]

    # 1. site groups, per aggregation router
    by_agg: dict[str, list[int]] = {}
    for i in site:
        by_agg.setdefault(topo.agg_of_site.get(anoms[i].entity_id, anoms[i].entity_id), []).append(
            i
        )
    for members in by_agg.values():
        for chain in _chain(members, anoms, gap):
            for i in chain[1:]:
                uf.union(chain[0], i)

    # 2. region anomalies join the site group they overlap most
    site_groups = _units(uf, anoms, site)
    leftover: dict[str, list[int]] = {}
    for i in sorted(region, key=lambda k: (anoms[k].start, k)):
        a = anoms[i]
        best, best_overlap = None, 0
        for g in site_groups:
            if a.region_id in g.regions and _overlaps(a.start, a.end, g.start, g.end, gap):
                overlap = _overlap_steps(a.start, a.end, g.start, g.end)
                if overlap > best_overlap or best is None:
                    best, best_overlap = g, overlap
        if best is not None:
            uf.union(best.members[0], i)
        else:
            leftover.setdefault(str(a.region_id), []).append(i)
    for members in leftover.values():
        for chain in _chain(members, anoms, gap):
            for i in chain[1:]:
                uf.union(chain[0], i)

    # 3. core anomalies; DNS / AMF ones pull in everything that overlaps them
    regional = site + region
    core_chains = _chain(core, anoms, gap)
    upf_only: list[list[int]] = []
    for chain in core_chains:
        for i in chain[1:]:
            uf.union(chain[0], i)
        is_global = any(
            topo.node_type.get(anoms[i].entity_id) in ("core_dns", "core_amf") for i in chain
        )
        if not is_global:
            upf_only.append(chain)
            continue
        c_start = min(anoms[i].start for i in chain)
        c_end = max(anoms[i].end for i in chain)
        for unit in _units(uf, anoms, regional):
            if _overlaps(c_start, c_end, unit.start, unit.end, gap):
                uf.union(chain[0], unit.members[0])

    # 4. several regions at the same moment: one nationwide group
    units = _units(uf, anoms, regional)
    for u in units:
        active = [v for v in units if v.start <= u.start <= v.end + gap]
        if len(set().union(*(v.regions for v in active))) >= cfg.nationwide_min_regions:
            for v in active:
                uf.union(u.members[0], v.members[0])

    # 5. UPF-only core groups
    units = _units(uf, anoms, regional)
    for chain in upf_only:
        c_start = min(anoms[i].start for i in chain)
        c_end = max(anoms[i].end for i in chain)
        served = {r for i in chain for r in topo.upf_regions.get(anoms[i].entity_id, ())}
        best, best_overlap = None, 0
        for u in units:
            if u.regions & served and _overlaps(c_start, c_end, u.start, u.end, gap):
                overlap = _overlap_steps(c_start, c_end, u.start, u.end)
                if overlap > best_overlap or best is None:
                    best, best_overlap = u, overlap
        if best is not None:
            uf.union(best.members[0], chain[0])

    groups: dict[int, list[int]] = {}
    for i in range(len(anoms)):
        groups.setdefault(uf.find(i), []).append(i)
    ordered = [sorted(g) for g in groups.values()]
    ordered.sort(key=lambda g: (min(anoms[i].start for i in g), g[0]))
    return ordered


# --- scoring and wording ---------------------------------------------------------------------

_VERB = {"drop": ("drops", "drop"), "spike": ("spikes", "spike")}


def _join(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _duration(hours: float) -> str:
    if hours < 1:
        return f"{max(round(hours * 60 / 5) * 5, 5)} min"
    half_hours = round(hours * 2) / 2
    return f"{half_hours:g} h"


def severity_score(
    group: list[Anomaly], hours: float, n_entities: int, cfg: DetectorConfig
) -> float:
    peak = min(max(abs(a.peak_z) for a in group), cfg.peak_z_cap)
    return round(2 * math.log1p(peak) + math.log1p(hours) + math.log1p(n_entities), 2)


def severity_label(score: float, cfg: DetectorConfig) -> str:
    if score >= cfg.high_score:
        return "high"
    return "medium" if score >= cfg.medium_score else "low"


def summarize(
    group: list[Anomaly], regions: list[str], nationwide: bool, hours: float, cfg: DetectorConfig
) -> str:
    labels = {m.name: m.label for m in (*cfg.cell_metrics, *cfg.core_metrics)}
    phrases: list[str] = []
    for direction in ("drop", "spike"):
        names = []
        for name in labels:  # canonical order
            if any(a.metric == name and a.direction == direction for a in group):
                names.append(labels[name])
        if names:
            verb = _VERB[direction][0 if len(names) == 1 else 1]
            phrases.append(f"{_join(names)} {verb}")
    what = "; ".join(phrases)

    sites = sorted({a.entity_id for a in group if a.entity_type == "site"})
    cores = sorted({a.entity_id for a in group if a.entity_type == "core_node"})
    region_ents = sorted({a.entity_id for a in group if a.entity_type == "region"})
    if sites:
        shown = ", ".join(sites[: cfg.summary_max_sites])
        more = (
            f" and {len(sites) - cfg.summary_max_sites} more"
            if len(sites) > cfg.summary_max_sites
            else ""
        )
        noun = "site" if len(sites) == 1 else "sites"
        where = f"on {len(sites)} {noun}"
        if nationwide:
            where += f" across {len(regions) or 'all'} regions"
        else:
            where += " in " + " and ".join(regions)
        where += f" ({shown}{more})"
        if cores:
            where += " and on " + ", ".join(cores)
    elif region_ents:
        where = "in region " + " and ".join(region_ents)
        if cores:
            where += " and on " + ", ".join(cores)
    else:
        where = "on " + ", ".join(cores)
    if nationwide:
        return f"Nationwide: {what} {where} for {_duration(hours)}"
    return f"{what[0].upper()}{what[1:]} {where} for {_duration(hours)}"


def build_alerts(
    anoms: list[Anomaly], ts: pd.DatetimeIndex, topo: Topology, cfg: DetectorConfig
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Alerts and anomalies as DataFrames shaped like the `alerts` and `anomalies` tables."""
    if not anoms:
        return pd.DataFrame(columns=ALERT_COLUMNS), pd.DataFrame(columns=ANOMALY_COLUMNS)
    step = ts[1] - ts[0] if len(ts) > 1 else pd.Timedelta(minutes=15)
    hours_per_step = step.total_seconds() / 3600.0

    alert_rows: list[dict[str, object]] = []
    alert_of = np.zeros(len(anoms), dtype=int)
    for idx in group_anomalies(anoms, topo, cfg):
        group = [anoms[i] for i in idx]
        start, end = min(a.start for a in group), max(a.end for a in group) + 1
        hours = (end - start) * hours_per_step
        cores = {a.entity_id for a in group if a.entity_type == "core_node"}
        regions = sorted({a.region_id for a in group if a.region_id is not None})
        has_global = any(topo.node_type.get(c) in ("core_dns", "core_amf") for c in cores)
        nationwide = has_global or len(regions) >= cfg.nationwide_min_regions or not regions
        entities = sorted(
            {a.entity_id for a in group if a.entity_type == "site"}
            | {a.entity_id for a in group if a.entity_type == "region"}
            | cores
        )
        score = severity_score(group, hours, len(entities), cfg)
        alert_rows.append(
            {
                "start_at": ts[start],
                "end_at": ts[0] + end * step,
                "region_ids": [] if nationwide else regions,
                "entity_ids": entities,
                "metrics": sorted({a.metric for a in group}),
                "severity": severity_label(score, cfg),
                "score": score,
                "n_anomalies": len(group),
                "summary": summarize(group, regions, nationwide, hours, cfg),
                "status": "new",
                "_members": idx,
            }
        )
    alert_rows.sort(key=lambda r: (r["start_at"], r["entity_ids"]))
    for n, row in enumerate(alert_rows, start=1):
        row["alert_id"] = f"ALR-{n:04d}"
        for i in row["_members"]:  # type: ignore[attr-defined]
            alert_of[i] = n - 1
    alerts = pd.DataFrame(alert_rows)
    alerts = alerts[ALERT_COLUMNS]

    order = sorted(
        range(len(anoms)),
        key=lambda i: (
            anoms[i].start,
            anoms[i].entity_id,
            anoms[i].metric,
            anoms[i].direction,
            anoms[i].end,
        ),
    )
    rows = []
    for n, i in enumerate(order, start=1):
        a = anoms[i]
        rows.append(
            {
                "anomaly_id": f"ANM-{n:06d}",
                "alert_id": alert_rows[alert_of[i]]["alert_id"],
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "region_id": a.region_id,
                "metric": a.metric,
                "direction": a.direction,
                "start_at": ts[a.start],
                "end_at": ts[a.end] + step,
                "n_steps": a.n_steps,
                "peak_z": a.peak_z,
                "baseline_value": a.baseline_value,
                "observed_value": a.observed_value,
            }
        )
    return alerts, pd.DataFrame(rows, columns=ANOMALY_COLUMNS)
