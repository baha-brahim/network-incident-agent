"""Score the detector against the planted scenarios. The only module that reads ground truth.

An alert matches a scenario when their time ranges overlap and they share scope:
- scenario on a set of sites: the alert's sites intersect the scenario's sites (links and
  routers are resolved to the sites behind them). An alert with only region-level entities
  matches if its region is one of the scenario's regions.
- nationwide scenario (DNS, public holiday): the alert must be nationwide, core-level or
  span two or more regions.
"""

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from incident_agent.detector.config import DetectorConfig
from incident_agent.detector.pipeline import Prepared, detect_prepared, prepare
from incident_agent.detector.series import DetectorInput, Topology
from incident_agent.simulator.world import World

NOT_DETECTABLE = {"alarm_storm"}  # no KPI impact by design
NATIONWIDE_KINDS = {"dns_degradation", "public_holiday"}
NATIONWIDE_SITE_FRACTION = 0.75
_GROUP_RE = re.compile(r"Overlaps in time with group '([^']+)'")


@dataclass(frozen=True)
class ScenarioScope:
    scenario_id: str
    kind: str
    is_incident: bool
    difficulty: str
    impact_start: pd.Timestamp
    end: pd.Timestamp
    sites: frozenset[str]
    regions: frozenset[str]
    nationwide: bool
    detectable: bool
    root_site: str | None
    overlap_group: str | None


def scenario_scopes(world: World, topo: Topology) -> list[ScenarioScope]:
    site_of_cell = dict(zip(world.cells["cell_id"], world.cells["site_id"], strict=True))
    n_sites = len(topo.agg_of_site)
    out: list[ScenarioScope] = []
    for sc in world.scenarios.to_dict(orient="records"):
        sites: set[str] = set()
        core_hit = False
        for node in sc["affected_node_ids"]:
            if node in site_of_cell:
                sites.add(site_of_cell[node])
            else:
                sites.update(topo.sites_under(node))
                core_hit = core_hit or topo.node_type.get(node, "").startswith("core_")
        nationwide = (
            sc["kind"] in NATIONWIDE_KINDS
            or core_hit
            or (n_sites > 0 and len(sites) >= NATIONWIDE_SITE_FRACTION * n_sites)
        )
        root = sc["root_cause_node_id"]
        match = _GROUP_RE.search(str(sc["notes"]))
        out.append(
            ScenarioScope(
                scenario_id=sc["scenario_id"],
                kind=sc["kind"],
                is_incident=bool(sc["is_incident"]),
                difficulty=sc["difficulty"],
                impact_start=sc["impact_start_at"],
                end=sc["end_at"],
                sites=frozenset(sites),
                regions=frozenset(sc["affected_region_ids"]),
                nationwide=nationwide,
                detectable=sc["kind"] not in NOT_DETECTABLE,
                root_site=root
                if isinstance(root, str) and topo.node_type.get(root) == "site"
                else None,
                overlap_group=match.group(1) if match else None,
            )
        )
    return out


def match_alerts(
    alerts: pd.DataFrame, scopes: list[ScenarioScope], topo: Topology
) -> dict[str, list[str]]:
    """alert_id -> ids of the detectable scenarios it matches."""
    matches: dict[str, list[str]] = {}
    for al in alerts.to_dict(orient="records"):
        entities = list(al["entity_ids"])
        sites = {e for e in entities if topo.node_type.get(e) == "site"}
        regions = set(al["region_ids"]) | {e for e in entities if e not in topo.node_type}
        wide = len(al["region_ids"]) == 0 or len(al["region_ids"]) >= 2
        hit: list[str] = []
        for sc in scopes:
            if not sc.detectable:
                continue
            if not (al["start_at"] < sc.end and al["end_at"] > sc.impact_start):
                continue
            if sc.nationwide:
                ok = wide
            elif sites:
                ok = bool(sites & sc.sites)
            else:
                ok = bool(regions & sc.regions)
            if ok:
                hit.append(sc.scenario_id)
        matches[al["alert_id"]] = hit
    return matches


def _pct(values: list[float], q: float) -> float | None:
    return float(np.percentile(values, q)) if values else None


@dataclass
class Evaluation:
    """Metrics for one world and one detector config."""

    seed: int | None
    n_alerts: int
    alerts_per_day: float
    n_detectable: int
    n_detected: int
    n_incidents: int
    n_incidents_detected: int
    n_matched_alerts: int
    n_incident_alerts: int
    recall: float
    recall_incidents: float
    precision: float
    precision_incidents: float
    f1: float
    f2: float
    delay_median_min: float | None
    delay_p90_min: float | None
    confirm_median_min: float | None
    fragmentation: float
    merged_alerts: list[dict[str, Any]]
    by_kind: dict[str, dict[str, Any]]
    by_difficulty: dict[str, dict[str, Any]]
    overlap_pairs: list[dict[str, Any]]
    missed: list[dict[str, Any]]
    false_positives: list[dict[str, Any]] = field(default_factory=list)
    delays: list[float] = field(default_factory=list)
    fragments: list[int] = field(default_factory=list)
    confirm_delays: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _f_beta(p: float, r: float, beta: float) -> float:
    return (1 + beta**2) * p * r / (beta**2 * p + r) if p + r > 0 else 0.0


def evaluate_alerts(
    alerts: pd.DataFrame,
    world: World,
    topo: Topology,
    cfg: DetectorConfig,
    n_days: float,
    seed: int | None = None,
) -> Evaluation:
    scopes = scenario_scopes(world, topo)
    by_id = {s.scenario_id: s for s in scopes}
    matches = match_alerts(alerts, scopes, topo)
    step = pd.Timedelta(minutes=15)

    scenario_alerts: dict[str, list[str]] = {s.scenario_id: [] for s in scopes if s.detectable}
    for alert_id, hit in matches.items():
        for sid in hit:
            scenario_alerts[sid].append(alert_id)
    alert_row = {a["alert_id"]: a for a in alerts.to_dict(orient="records")}
    detected = {sid for sid, al in scenario_alerts.items() if al}

    delays: list[float] = []
    confirm: list[float] = []
    for sid in detected:
        first = min(alert_row[a]["start_at"] for a in scenario_alerts[sid])
        delay = (first - by_id[sid].impact_start) / pd.Timedelta(minutes=1)
        delays.append(delay)
        confirm.append(delay + cfg.min_steps * step / pd.Timedelta(minutes=1))

    n_alerts = len(alerts)
    matched = [a for a, hit in matches.items() if hit]
    incident_alerts = [a for a, hit in matches.items() if any(by_id[s].is_incident for s in hit)]
    n_detectable = len(scenario_alerts)
    incidents = [s for s in scopes if s.detectable and s.is_incident]
    n_inc_detected = sum(1 for s in incidents if s.scenario_id in detected)
    recall = len(detected) / n_detectable if n_detectable else 0.0
    precision = len(matched) / n_alerts if n_alerts else 0.0

    def breakdown(attr: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for s in scopes:
            if not s.detectable:
                continue
            row = out.setdefault(getattr(s, attr), {"n": 0, "detected": 0})
            row["n"] += 1
            row["detected"] += int(s.scenario_id in detected)
        for row in out.values():
            row["recall"] = row["detected"] / row["n"]
        return dict(sorted(out.items()))

    merged = [
        {
            "alert_id": a,
            "scenarios": hit,
            "summary": alert_row[a]["summary"],
        }
        for a, hit in matches.items()
        if len(hit) > 1
    ]

    pairs: list[dict[str, Any]] = []
    groups: dict[str, list[ScenarioScope]] = {}
    for s in scopes:
        if s.overlap_group:
            groups.setdefault(s.overlap_group, []).append(s)
    for name, members in sorted(groups.items()):
        ids = [m.scenario_id for m in members]
        shared = [a for a, hit in matches.items() if set(ids) <= set(hit)]
        pairs.append(
            {
                "group": name,
                "scenarios": [
                    {
                        "scenario_id": m.scenario_id,
                        "kind": m.kind,
                        "detected": m.scenario_id in detected,
                        "alerts": sorted(scenario_alerts.get(m.scenario_id, [])),
                    }
                    for m in members
                ],
                "kept_apart": len(shared) == 0 and all(m.scenario_id in detected for m in members),
                "shared_alerts": shared,
            }
        )

    storm_sites = {s.root_site for s in scopes if s.kind in NOT_DETECTABLE and s.root_site}
    fps: list[dict[str, Any]] = []
    for a, hit in matches.items():
        if hit:
            continue
        row = alert_row[a]
        storm = [
            s.scenario_id
            for s in scopes
            if s.kind in NOT_DETECTABLE
            and s.root_site in set(row["entity_ids"]) & storm_sites
            and row["start_at"] < s.end
            and row["end_at"] > s.impact_start
        ]
        fps.append(
            {
                "alert_id": a,
                "start_at": row["start_at"].isoformat(),
                "severity": row["severity"],
                "summary": row["summary"],
                "during_alarm_storm": storm,
            }
        )

    missed = [
        {"scenario_id": s.scenario_id, "kind": s.kind, "difficulty": s.difficulty}
        for s in scopes
        if s.detectable and s.scenario_id not in detected
    ]
    return Evaluation(
        seed=seed,
        n_alerts=n_alerts,
        alerts_per_day=n_alerts / n_days if n_days else 0.0,
        n_detectable=n_detectable,
        n_detected=len(detected),
        n_incidents=len(incidents),
        n_incidents_detected=n_inc_detected,
        n_matched_alerts=len(matched),
        n_incident_alerts=len(incident_alerts),
        recall=recall,
        recall_incidents=n_inc_detected / len(incidents) if incidents else 0.0,
        precision=precision,
        precision_incidents=len(incident_alerts) / n_alerts if n_alerts else 0.0,
        f1=_f_beta(precision, recall, 1.0),
        f2=_f_beta(precision, recall, 2.0),
        delay_median_min=_pct(delays, 50),
        delay_p90_min=_pct(delays, 90),
        confirm_median_min=_pct(confirm, 50),
        fragmentation=(
            float(np.mean([len(scenario_alerts[s]) for s in detected])) if detected else 0.0
        ),
        merged_alerts=merged,
        by_kind=breakdown("kind"),
        by_difficulty=breakdown("difficulty"),
        overlap_pairs=pairs,
        missed=missed,
        false_positives=fps,
        delays=sorted(delays),
        fragments=[len(scenario_alerts[s]) for s in sorted(detected)],
        confirm_delays=sorted(confirm),
    )


def window_days(world: World) -> float:
    ts = world.core_kpis["ts"] if len(world.core_kpis) else world.cell_kpis["ts"]
    return float((ts.max() - ts.min()) / pd.Timedelta(days=1)) + 15 / 1440


@dataclass(frozen=True)
class PreparedWorld:
    """A world with its detector baseline computed once, so thresholds can be swept cheaply."""

    seed: int
    world: World
    prepared: Prepared
    n_days: float


def prepare_world(world: World, seed: int, cfg: DetectorConfig | None = None) -> PreparedWorld:
    cfg = cfg or DetectorConfig()
    prep = prepare(DetectorInput.from_world(world), cfg)
    return PreparedWorld(seed, world, prep, window_days(world))


def evaluate_prepared(pw: PreparedWorld, cfg: DetectorConfig) -> Evaluation:
    result = detect_prepared(pw.prepared, cfg)
    return evaluate_alerts(result.alerts, pw.world, pw.prepared.topology, cfg, pw.n_days, pw.seed)


def pool(evals: list[Evaluation]) -> dict[str, Any]:
    """Pooled metrics over several worlds (sums of counts, not averages of ratios)."""
    n_alerts = sum(e.n_alerts for e in evals)
    detectable = sum(e.n_detectable for e in evals)
    detected = sum(e.n_detected for e in evals)
    matched = sum(e.n_matched_alerts for e in evals)
    incidents = sum(e.n_incidents for e in evals)
    inc_det = sum(e.n_incidents_detected for e in evals)
    precision = matched / n_alerts if n_alerts else 0.0
    recall = detected / detectable if detectable else 0.0
    kinds: dict[str, dict[str, Any]] = {}
    diffs: dict[str, dict[str, Any]] = {}
    for e in evals:
        for src, dst in ((e.by_kind, kinds), (e.by_difficulty, diffs)):
            for key, row in src.items():
                d = dst.setdefault(key, {"n": 0, "detected": 0})
                d["n"] += row["n"]
                d["detected"] += row["detected"]
    for table in (kinds, diffs):
        for row in table.values():
            row["recall"] = row["detected"] / row["n"]
    return {
        "seeds": [e.seed for e in evals],
        "n_alerts": n_alerts,
        "alerts_per_day": float(np.mean([e.alerts_per_day for e in evals])) if evals else 0.0,
        "n_detectable": detectable,
        "n_detected": detected,
        "n_incidents": incidents,
        "n_incidents_detected": inc_det,
        "recall": recall,
        "recall_incidents": inc_det / incidents if incidents else 0.0,
        "precision": precision,
        "precision_incidents": (
            sum(e.n_incident_alerts for e in evals) / n_alerts if n_alerts else 0.0
        ),
        "f1": _f_beta(precision, recall, 1.0),
        "f2": _f_beta(precision, recall, 2.0),
        "delay_median_min": _pct([d for e in evals for d in e.delays], 50),
        "delay_p90_min": _pct([d for e in evals for d in e.delays], 90),
        "confirm_median_min": _pct([d for e in evals for d in e.confirm_delays], 50),
        "fragmentation": (
            float(np.mean(frag)) if (frag := [f for e in evals for f in e.fragments]) else 0.0
        ),
        "n_merged_alerts": sum(len(e.merged_alerts) for e in evals),
        "by_kind": dict(sorted(kinds.items())),
        "by_difficulty": dict(sorted(diffs.items())),
    }
