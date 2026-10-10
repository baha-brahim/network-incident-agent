"""Detector unit tests (no database, no network)."""

import numpy as np
import pandas as pd
import pytest

from incident_agent.detector import DetectorConfig, DetectorInput, detect
from incident_agent.detector.alerts import group_anomalies
from incident_agent.detector.anomalies import Anomaly, extract_anomalies, find_runs
from incident_agent.detector.baseline import nanmedian_rows, score_series
from incident_agent.detector.config import MetricSpec
from incident_agent.detector.evaluate import (
    evaluate_alerts,
    match_alerts,
    scenario_scopes,
)
from incident_agent.detector.series import SeriesSet, Topology
from incident_agent.simulator.world import World
from tests.fixtures_world import make_fixture_world

VOLUME = MetricSpec("dl_volume_mb", ("drop", "spike"), rel_floor=0.02)
AVAILABILITY = MetricSpec("availability_pct", ("drop",), abs_floor=1.0)


def make_series(rows: list[np.ndarray], specs: list[MetricSpec], days: int = 14) -> SeriesSet:
    """Series on a 15-minute grid starting Monday 2026-09-07 00:00 Tunis time."""
    ts = pd.date_range("2026-09-06 23:00", periods=days * 96, freq="15min", tz="UTC")
    n = len(rows)
    return SeriesSet(
        ts=ts,
        entity_type=np.array(["site"] * n, dtype=object),
        entity_id=np.array([f"S-TUN-{i:03d}" for i in range(n)], dtype=object),
        region_id=np.array(["TUN"] * n, dtype=object),
        metric=np.array([s.name for s in specs], dtype=object),
        spec=tuple(specs),
        values=np.vstack(rows),
    )


def daily_curve(days: int = 14, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    slot = np.tile(np.arange(96), days)
    base = 1000 + 600 * np.sin(2 * np.pi * slot / 96)
    return base * rng.normal(1.0, 0.02, size=base.shape)


# --- baseline and z-scores ------------------------------------------------------------------


def test_nanmedian_rows_ignores_nan() -> None:
    a = np.array([[1.0, np.nan, 3.0, 2.0], [np.nan, np.nan, np.nan, np.nan], [4.0, 6.0, 5.0, 7.0]])
    out = nanmedian_rows(a)
    assert out[0] == 2.0
    assert np.isnan(out[1])
    assert out[2] == 5.5


def test_normal_series_has_small_z_and_drop_has_large_negative_z() -> None:
    x = daily_curve()
    drop = slice(8 * 96 + 40, 8 * 96 + 52)  # a Tuesday, 3 hours
    x[drop] *= 0.3
    cfg = DetectorConfig()
    scored = score_series(make_series([x], [VOLUME]), cfg)
    z = scored.z[0]
    mask = np.ones(len(z), dtype=bool)
    mask[drop] = False
    assert np.nanpercentile(np.abs(z[mask]), 99) < 4
    assert z[drop].max() < -5
    # The baseline at the dropped steps is the normal level, not the dropped one.
    assert scored.baseline[0, drop].mean() > 0.8 * (x[drop].mean() / 0.3)


def test_floor_stops_constant_series_from_exploding() -> None:
    x = np.full(14 * 96, 100.0)
    x[300] = 97.8  # one cell of a site blips
    scored = score_series(make_series([x], [AVAILABILITY]), DetectorConfig())
    assert abs(scored.z[0, 300]) < 3  # floor of 1.0 point: z = -2.2


# --- anomalies ------------------------------------------------------------------------------


def test_planted_drop_is_found_with_the_right_interval() -> None:
    x = daily_curve()
    start, end = 9 * 96 + 60, 9 * 96 + 83  # a Wednesday, 24 steps
    x[start : end + 1] *= 0.2
    series = make_series([x], [VOLUME])
    found = extract_anomalies(score_series(series, DetectorConfig()), DetectorConfig())
    assert len(found) == 1
    a = found[0]
    assert a.direction == "drop"
    assert (a.start, a.end) == (start, end)
    assert a.peak_z < -10
    assert a.observed_value < a.baseline_value


def test_one_step_blip_does_not_fire_but_a_min_steps_run_does() -> None:
    cfg = DetectorConfig(z_threshold=4.0, min_steps=3)
    blip = daily_curve()
    blip[400] *= 0.2
    short = daily_curve(seed=1)
    short[400:402] *= 0.2  # two steps
    run = daily_curve(seed=2)
    run[400:403] *= 0.2  # three steps
    series = make_series([blip, short, run], [VOLUME] * 3)
    found = extract_anomalies(score_series(series, cfg), cfg)
    assert [a.entity_id for a in found] == ["S-TUN-002"]


def test_single_step_gap_is_bridged() -> None:
    cfg = DetectorConfig(min_steps=3)
    x = daily_curve()
    x[400:404] *= 0.2
    x[405:408] *= 0.2  # one normal step at 404
    series = make_series([x], [VOLUME])
    found = extract_anomalies(score_series(series, cfg), cfg)
    assert len(found) == 1
    assert (found[0].start, found[0].end) == (400, 407)


def test_nan_steps_are_skipped_without_errors() -> None:
    x = daily_curve()
    x[200:210] = np.nan
    x[700:710] *= 0.2
    cfg = DetectorConfig()
    found = extract_anomalies(score_series(make_series([x], [VOLUME]), cfg), cfg)
    assert [(a.start, a.end) for a in found] == [(700, 709)]


def test_only_directions_of_interest_fire() -> None:
    x = np.full(14 * 96, 100.0)
    x[400:410] = 150.0  # availability above normal is not an anomaly
    cfg = DetectorConfig()
    assert extract_anomalies(score_series(make_series([x], [AVAILABILITY]), cfg), cfg) == []


def test_find_runs_does_not_cross_rows() -> None:
    mask = np.array([[0, 1, 1, 1], [1, 1, 0, 0], [0, 0, 0, 1]], dtype=bool)
    assert find_runs(mask) == [(0, 1, 3), (1, 0, 1), (2, 3, 3)]


# --- grouping -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def topo() -> Topology:
    return Topology.from_nodes(make_fixture_world().nodes)


def anomaly(
    entity: str, kind: str, region: str | None, metric: str, start: int, end: int
) -> Anomaly:
    return Anomaly(kind, entity, region, metric, "drop", start, end, -9.0, 100.0, 10.0)


def test_unrelated_regions_stay_separate_alerts(topo: Topology) -> None:
    anoms = [
        anomaly("S-TUN-001", "site", "TUN", "dl_volume_mb", 10, 20),
        anomaly("S-SFX-001", "site", "SFX", "dl_volume_mb", 12, 22),
    ]
    assert len(group_anomalies(anoms, topo, DetectorConfig())) == 2


def test_same_link_or_router_and_overlap_are_one_alert(topo: Topology) -> None:
    anoms = [
        anomaly("S-TUN-001", "site", "TUN", "dl_volume_mb", 10, 20),
        anomaly("S-TUN-002", "site", "TUN", "availability_pct", 11, 21),
        anomaly("S-TUN-003", "site", "TUN", "dl_volume_mb", 15, 25),  # other link, same router
    ]
    assert group_anomalies(anoms, topo, DetectorConfig()) == [[0, 1, 2]]


def test_same_region_far_apart_in_time_is_separate(topo: Topology) -> None:
    anoms = [
        anomaly("S-TUN-001", "site", "TUN", "dl_volume_mb", 10, 20),
        anomaly("S-TUN-002", "site", "TUN", "dl_volume_mb", 200, 210),
    ]
    assert len(group_anomalies(anoms, topo, DetectorConfig())) == 2


def test_region_level_anomaly_joins_the_overlapping_site_group(topo: Topology) -> None:
    anoms = [
        anomaly("S-TUN-001", "site", "TUN", "dl_volume_mb", 10, 20),
        anomaly("TUN", "region", "TUN", "dl_volume_mb", 11, 19),
    ]
    assert group_anomalies(anoms, topo, DetectorConfig()) == [[0, 1]]


def test_dns_anomaly_pulls_in_every_region(topo: Topology) -> None:
    anoms = [
        anomaly("S-TUN-001", "site", "TUN", "latency_ms", 10, 20),
        anomaly("S-SFX-001", "site", "SFX", "latency_ms", 10, 20),
        anomaly("CORE-DNS-01", "core_node", None, "resolution_ms", 9, 21),
    ]
    assert group_anomalies(anoms, topo, DetectorConfig()) == [[0, 1, 2]]


def test_three_regions_at_once_are_one_nationwide_alert(topo: Topology) -> None:
    cfg = DetectorConfig(nationwide_min_regions=3)
    anoms = [
        anomaly("TUN", "region", "TUN", "dl_volume_mb", 10, 20),
        anomaly("SFX", "region", "SFX", "dl_volume_mb", 10, 20),
        anomaly("SAH", "region", "SAH", "dl_volume_mb", 11, 21),
    ]
    assert len(group_anomalies(anoms, topo, cfg)) == 1
    assert len(group_anomalies(anoms[:2], topo, cfg)) == 2


# --- whole pipeline on the fixture world ------------------------------------------------------


@pytest.fixture(scope="module")
def world() -> World:
    return make_fixture_world()


def test_fixture_world_alerts(world: World) -> None:
    result = detect(DetectorInput.from_world(world))
    alerts = result.alerts
    assert list(alerts.columns)[:3] == ["alert_id", "start_at", "end_at"]
    assert alerts["alert_id"].is_unique and result.anomalies["anomaly_id"].is_unique
    assert set(result.anomalies["alert_id"]) == set(alerts["alert_id"])
    cut = alerts[alerts["entity_ids"].apply(lambda e: "S-TUN-001" in e)]
    assert len(cut) == 1
    row = cut.iloc[0]
    assert {e for e in row["entity_ids"] if e.startswith("S-")} == {"S-TUN-001", "S-TUN-002"}
    assert "availability" in row["summary"] and "2 sites in TUN" in row["summary"]
    assert row["start_at"] == pd.Timestamp("2026-09-02 17:00", tz="UTC")
    assert row["end_at"] == pd.Timestamp("2026-09-02 21:00", tz="UTC")
    dns = alerts[alerts["entity_ids"].apply(lambda e: "CORE-DNS-01" in e)]
    assert len(dns) == 1 and dns.iloc[0]["region_ids"] == []


def test_detection_is_deterministic(world: World) -> None:
    inp = DetectorInput.from_world(world)
    a, b = detect(inp), detect(inp)
    pd.testing.assert_frame_equal(a.alerts, b.alerts)
    pd.testing.assert_frame_equal(a.anomalies, b.anomalies)


# --- matching rules -------------------------------------------------------------------------


def alert_row(
    alert_id: str, start: str, end: str, regions: list[str], entities: list[str]
) -> dict[str, object]:
    return {
        "alert_id": alert_id,
        "start_at": pd.Timestamp(start, tz="UTC"),
        "end_at": pd.Timestamp(end, tz="UTC"),
        "region_ids": regions,
        "entity_ids": entities,
        "summary": "x",
        "severity": "low",
    }


def test_matching_rules_on_fixture_scenarios(world: World, topo: Topology) -> None:
    scopes = {s.scenario_id: s for s in scenario_scopes(world, topo)}
    # Links resolve to the sites behind them; a cell resolves to its site; DNS is nationwide.
    assert scopes["SCN-001"].sites == {"S-TUN-001", "S-TUN-002"}
    assert scopes["SCN-004"].sites == {"S-TUN-003"}
    assert scopes["SCN-005"].sites == {"S-TUN-001", "S-TUN-002", "S-TUN-003"}
    assert scopes["SCN-002"].nationwide
    cut = ("2026-09-02 17:00", "2026-09-02 21:00")
    alerts = pd.DataFrame(
        [
            alert_row("A1", *cut, ["TUN"], ["S-TUN-002"]),  # shares a site: match
            alert_row("A2", *cut, ["SFX"], ["S-SFX-001"]),  # other region: no match
            alert_row("A3", "2026-09-04 01:00", "2026-09-04 03:00", ["TUN"], ["S-TUN-002"]),  # late
            alert_row("A4", *cut, [], ["CORE-DNS-01"]),  # core-level: not a site scenario
            alert_row("A5", "2026-09-02 12:00", "2026-09-02 13:00", [], ["CORE-DNS-01"]),
            alert_row("A6", "2026-09-02 12:00", "2026-09-02 13:00", ["TUN"], ["S-TUN-001"]),
            alert_row("A7", "2026-09-02 12:00", "2026-09-02 13:00", ["TUN", "SFX"], ["TUN", "SFX"]),
        ]
    )
    matches = match_alerts(alerts, list(scopes.values()), topo)
    assert matches["A1"] == ["SCN-001"]
    assert matches["A2"] == []
    assert matches["A3"] == []
    assert "SCN-001" not in matches["A4"]
    assert matches["A5"] == ["SCN-002"]  # core-level alert matches the nationwide scenario
    assert matches["A6"] == []  # a single-region alert does not match a nationwide scenario
    assert matches["A7"] == ["SCN-002"]  # multi-region does


def test_evaluation_metrics_on_fixture_world(world: World, topo: Topology) -> None:
    cfg = DetectorConfig()
    result = detect(DetectorInput.from_world(world), cfg)
    ev = evaluate_alerts(result.alerts, world, topo, cfg, n_days=4.0)
    assert ev.n_detectable == 5  # no alarm storm in the fixture, five detectable scenarios
    kinds = {k: v["detected"] for k, v in ev.by_kind.items()}
    assert kinds["fiber_cut"] == kinds["dns_degradation"] == 1
    assert kinds["planned_maintenance"] == kinds["stadium_event"] == 1
    assert kinds["config_push"] == 0  # the fixture's config push has no KPI effect
    assert [m["scenario_id"] for m in ev.missed] == ["SCN-005"]
    assert ev.recall == pytest.approx(0.8)
    assert ev.precision == pytest.approx(0.8)  # the SFX blackout matches no scenario
    assert len(ev.false_positives) == 1
