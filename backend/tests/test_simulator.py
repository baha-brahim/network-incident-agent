"""Unit tests for the synthetic network (no DB needed)."""

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from incident_agent.simulator.build import build_world
from incident_agent.simulator.digest import table_digests, world_digest
from incident_agent.simulator.io import read_world, write_world
from incident_agent.simulator.world import SCHEMA, World

STEPS_PER_DAY = 96
STEP = pd.Timedelta(minutes=15)


@pytest.fixture(scope="module")
def world() -> World:
    return build_world(seed=42)


@pytest.fixture(scope="module")
def other_world() -> World:
    return build_world(seed=7)


class Kpis:
    """(cells, steps) arrays over cell_kpis, which is stored cell-major."""

    def __init__(self, w: World) -> None:
        self.cell_ids = w.cells["cell_id"].tolist()
        self.site_of = dict(zip(w.cells["cell_id"], w.cells["site_id"], strict=True))
        n = len(self.cell_ids)
        self.arr = {
            c: w.cell_kpis[c].to_numpy().reshape(n, -1)
            for c in w.cell_kpis.columns
            if c not in ("ts", "cell_id")
        }
        self.ts = pd.DatetimeIndex(w.cell_kpis["ts"].iloc[: self.arr["dl_volume_mb"].shape[1]])

    def rows(self, sites: list[str]) -> list[int]:
        wanted = set(sites)
        return [i for i, c in enumerate(self.cell_ids) if self.site_of[c] in wanted]

    def idx(self, t: pd.Timestamp) -> int:
        return int((t - self.ts[0]) / STEP)

    def series(self, col: str, sites: list[str], t0: pd.Timestamp, t1: pd.Timestamp) -> np.ndarray:
        return self.arr[col][self.rows(sites)][:, self.idx(t0) : self.idx(t1)]

    def vs_baseline(
        self, col: str, sites: list[str], t0: pd.Timestamp, t1: pd.Timestamp
    ) -> tuple[float, float]:
        """Mean over the window and median of the same time-of-day window on other days."""
        data = self.arr[col][self.rows(sites)]
        i0, i1 = self.idx(t0), self.idx(t1)
        cur = float(np.nanmean(data[:, i0:i1]))
        others = [
            float(np.nanmean(data[:, i0 + k * STEPS_PER_DAY : i1 + k * STEPS_PER_DAY]))
            for k in range(-29, 30)
            if k != 0 and i0 + k * STEPS_PER_DAY >= 0 and i1 + k * STEPS_PER_DAY <= data.shape[1]
        ]
        return cur, float(np.median(others))

    def ratio(self, col: str, sites: list[str], t0: pd.Timestamp, t1: pd.Timestamp) -> float:
        cur, base = self.vs_baseline(col, sites, t0, t1)
        return cur / base


@pytest.fixture(scope="module")
def kpis(world: World) -> Kpis:
    return Kpis(world)


def scenarios(world: World, kind: str) -> list[dict[str, Any]]:
    df = world.scenarios
    return df[df["kind"] == kind].to_dict(orient="records")  # type: ignore[no-any-return]


def affected_sites(sc: dict[str, Any]) -> list[str]:
    return [n for n in sc["affected_node_ids"] if n.startswith("S-")]


def all_sites(world: World) -> list[str]:
    return world.nodes.loc[world.nodes["node_type"] == "site", "node_id"].tolist()


# ------------------------------------------------------------------ structure and determinism


def test_validate_and_tables(world: World) -> None:
    world.validate()
    assert len(world.regions) == 4
    assert len(world.cell_kpis) == len(world.cells) * 2880
    assert len(world.cells) == 3 * 48


def test_determinism(world: World) -> None:
    again = build_world(seed=42)
    for name, df in world.tables().items():
        pd.testing.assert_frame_equal(df, again.tables()[name], check_exact=True)


# Content digests of the default worlds (`simulator.digest`). The seed-42 and seed-7 databases and
# every recorded evaluation result depend on these exact worlds: a change that moves a digest
# changes them, so update these values only on purpose.
DEFAULT_WORLD_DIGESTS = {
    42: "f0cd559705141ef0e73d725364b8ee5e6d0553d7fb58af419aa1cd2121d3a46a",
    7: "0924d9858eedd14c73271ad30a25283074e5d3897dfa06f3270d255e7fd87809",
}
SEED_42_TABLE_DIGESTS = {
    "alarms": "c97ce801dd0d2ae7368621fac37257755848ee413839c5ca4c73fd49b5f0b76a",
    "cell_kpis": "b5855c4d991d678f294056d3e12f6a2d48617057c36c3aaec9f4bad139f9c5a6",
    "cells": "3ad5f611b9ad3f8e56c39bd5a14897798e7435281259babe2ec3fe105517487d",
    "changes": "907d1f143ae8e1ff9611917080b9e1a55b185a5ba0ba4b27c2ba838b2798d2ca",
    "core_kpis": "97e96e940d587164d5bb36cd1410eed12f7b58da96f89e1b6b54026ea94548c1",
    "dataset_meta": "1ef298b899ef1b1f0f482ed871856448b37c65a85cc82fdf174ab07aaa295f71",
    "external_events": "f16f1adf60db064341a00351d59b770aa943b2a08b44730ef45a1e1ba2b99371",
    "maintenance": "7ab2726ab733ea17d8b8f1dbe3d2ee61a6d568772d7b58d2fc91175048f72a9c",
    "nodes": "5d6fdea9a3b6312eef265e2e9ca6a70cdf8043a1142097c927a6b4779169767f",
    "regions": "8800348421489837e5aacc19ca5d9c97f89d23b4cfb878a1b22b94f836b6a733",
    "scenarios": "8ea38dd488f6952d56a1f58f1daed6c49d12f559f892e769c9f7475a659a8b00",
}


def test_default_world_is_pinned(world: World, other_world: World) -> None:
    assert table_digests(world) == SEED_42_TABLE_DIGESTS
    assert world_digest(world) == DEFAULT_WORLD_DIGESTS[42]
    assert world_digest(other_world) == DEFAULT_WORLD_DIGESTS[7]


def test_different_seeds_differ(world: World, other_world: World) -> None:
    assert not world.cell_kpis["dl_volume_mb"].equals(other_world.cell_kpis["dl_volume_mb"])
    assert not world.scenarios["start_at"].equals(other_world.scenarios["start_at"])


def test_nan_only_in_quality_kpis_of_down_cells(world: World) -> None:
    c = world.cell_kpis
    quality = ["rrc_success_pct", "drop_rate_pct", "latency_ms"]
    down = (c["availability_pct"] == 0).to_numpy()
    assert down.any()
    for col in quality:
        assert (c[col].isna().to_numpy() == down).all(), col
    others = [col for col, _ in SCHEMA["cell_kpis"] if col not in (*quality, "ts", "cell_id")]
    assert np.isfinite(c[others].to_numpy()).all()
    assert np.isfinite(world.core_kpis["value"].to_numpy()).all()
    assert (c.loc[down, ["dl_volume_mb", "active_users", "prb_util_pct"]] == 0).all().all()
    # Partially available steps still report real measurements.
    partial = (c["availability_pct"] > 0) & (c["availability_pct"] < 100)
    assert partial.any() and c.loc[partial, quality].notna().all().all()
    assert (c["availability_pct"].between(0, 100)).all()
    for col in quality[:1]:
        assert c[col].dropna().between(0, 100).all()


def test_topology(world: World) -> None:
    nodes = world.nodes.set_index("node_id")
    for site in all_sites(world):
        chain = [site]
        while isinstance(nodes.loc[chain[-1], "parent_id"], str):
            chain.append(nodes.loc[chain[-1], "parent_id"])
        types = [nodes.loc[n, "node_type"] for n in chain]
        assert types == ["site", "transport_link", "agg_router", "core_upf"]
    assert set(world.cells["site_id"]) == set(all_sites(world))
    assert (world.cells.groupby("site_id").size() == 3).all()
    sites = nodes[nodes["node_type"] == "site"]
    assert sites["region_id"].value_counts().to_dict() == {
        "TUN": 18,
        "SAH": 12,
        "SFX": 10,
        "SUD": 8,
    }
    venue = [n for n in sites.index if sites.loc[n, "attrs"]["near_venue"]]
    assert 2 <= len(venue) <= 3
    assert all(sites.loc[n, "region_id"] == "TUN" for n in venue)
    media = nodes[nodes["node_type"] == "transport_link"]["attrs"].map(lambda a: a["medium"])
    assert {"fiber", "microwave"} <= set(media)
    assert (media == "fiber").sum() > (media == "microwave").sum()
    assert {"CORE-DNS-01", "CORE-AMF-01", "CORE-UPF-01", "CORE-UPF-02"} <= set(nodes.index)
    # Normal operation never goes below ~9 percentage points of PRB headroom at the busiest cell.
    assert world.cell_kpis["prb_util_pct"].groupby(world.cell_kpis["cell_id"]).median().max() < 50


# ---------------------------------------------------------------------------- scenario mix


def test_scenario_mix(world: World) -> None:
    sc = world.scenarios
    assert sc["is_incident"].sum() == 24
    assert (~sc["is_incident"]).sum() == 10
    diff = sc["difficulty"].value_counts(normalize=True)
    assert 0.3 <= diff["easy"] <= 0.5
    assert 0.3 <= diff["medium"] <= 0.5
    assert 0.1 <= diff["hard"] <= 0.3
    assert sc["scenario_id"].is_unique
    assert sc["start_at"].is_monotonic_increasing
    kinds = set(sc["kind"])
    assert {
        "fiber_cut", "power_outage", "config_push", "dns_degradation", "congestion",
        "link_degradation", "planned_maintenance", "stadium_event", "public_holiday",
        "alarm_storm",
    } == kinds  # fmt: skip


def test_exactly_two_overlaps_in_different_regions(world: World) -> None:
    rows = world.scenarios.to_dict(orient="records")
    overlaps = []
    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            if a["start_at"] < b["end_at"] and b["start_at"] < a["end_at"]:
                overlaps.append((a, b))
    assert len(overlaps) == 2
    for a, b in overlaps:
        assert set(a["affected_region_ids"]).isdisjoint(b["affected_region_ids"])


def test_evidence_ids_exist(world: World) -> None:
    key = {"alarms": "alarm_id", "changes": "change_id", "maintenance": "mw_id",
           "external_events": "event_id"}  # fmt: skip
    nodes = set(world.nodes["node_id"])
    for sc in world.scenarios.to_dict(orient="records"):
        for ref in [*sc["evidence"], *sc["confounders"]]:
            assert ref["id"] in set(getattr(world, ref["table"])[key[ref["table"]]]), sc
        if isinstance(sc["root_cause_node_id"], str):
            assert sc["root_cause_node_id"] in nodes
        assert set(sc["affected_node_ids"]) <= nodes
        known_tools = {
            "query_kpis", "get_topology", "get_alarms", "get_changes", "get_maintenance",
            "get_external_events", "get_anomalies", "search_runbooks",
        }  # fmt: skip
        assert sc["expected_tools"] and set(sc["expected_tools"]) <= known_tools
        if sc["kind"] in ("stadium_event", "public_holiday", "congestion"):
            assert "get_external_events" in sc["expected_tools"]
        assert sc["start_at"] <= sc["impact_start_at"] <= sc["end_at"]
        if sc["kind"] != "dns_degradation" or sc["difficulty"] != "hard":
            assert sc["evidence"], sc["scenario_id"]


def test_hard_incidents_have_confounders(world: World) -> None:
    sc = world.scenarios
    hard = sc[sc["is_incident"] & (sc["difficulty"] == "hard")]
    assert len(hard) >= 4
    assert all(len(c) >= 1 for c in hard["confounders"])
    alarms = world.alarms.set_index("alarm_id")
    changes = world.changes.set_index("change_id")
    for r in hard.to_dict(orient="records"):
        for c in r["confounders"]:
            t = (alarms.loc[c["id"], "raised_at"] if c["table"] == "alarms"
                 else changes.loc[c["id"], "executed_at"])  # fmt: skip
            lead = r["start_at"] - t
            assert pd.Timedelta(minutes=14) <= lead <= pd.Timedelta(minutes=91), r["scenario_id"]
            assert c["why"]
    easy = sc[sc["is_incident"] & (sc["difficulty"] != "hard")]
    assert all(len(c) == 0 for c in easy["confounders"])


# ------------------------------------------------------------------------ incident effects


def test_fiber_cut(world: World, kpis: Kpis) -> None:
    for sc in scenarios(world, "fiber_cut"):
        sites = affected_sites(sc)
        t0, t1 = sc["start_at"], sc["end_at"]
        assert pd.Timedelta(hours=2) <= t1 - t0 <= pd.Timedelta(hours=8)
        inside = kpis.series("availability_pct", sites, t0 + STEP, t1 - STEP)
        assert inside.max() == 0
        assert kpis.series("dl_volume_mb", sites, t0 + STEP, t1 - STEP).max() == 0
        # Evidence: LOS on the link, SITE_DOWN on every site within 1-2 minutes.
        alarms = world.alarms.set_index("alarm_id").loc[[e["id"] for e in sc["evidence"]]]
        los = alarms[alarms["alarm_type"] == "LINK_LOS"]
        assert (los["node_id"] == sc["root_cause_node_id"]).all() and (
            los["severity"] == "critical"
        ).all()
        down = alarms[alarms["alarm_type"] == "SITE_DOWN"]
        assert set(down["node_id"]) == set(sites)
        assert ((down["raised_at"] - t0) <= pd.Timedelta(minutes=2)).all()
        assert down["cleared_at"].notna().all()


def test_power_outage_battery_delay(world: World, kpis: Kpis) -> None:
    for sc in scenarios(world, "power_outage"):
        site = sc["root_cause_node_id"]
        t0, ti, t1 = sc["start_at"], sc["impact_start_at"], sc["end_at"]
        assert pd.Timedelta(hours=1) <= ti - t0 <= pd.Timedelta(hours=4)
        before = kpis.series("availability_pct", [site], t0 - STEP, ti - STEP)
        assert before.min() > 85  # only harmless micro-outages
        assert 0.6 < kpis.ratio("dl_volume_mb", [site], t0, ti - STEP) < 1.6
        assert kpis.series("availability_pct", [site], ti + STEP, t1 - STEP).max() == 0
        alarms = world.alarms.set_index("alarm_id").loc[[e["id"] for e in sc["evidence"]]]
        by_type = alarms.set_index("alarm_type")
        assert by_type.loc["MAINS_FAILURE", "raised_at"] == t0
        assert by_type.loc["BATTERY_LOW", "raised_at"] == ti - pd.Timedelta(minutes=15)
        assert abs(by_type.loc["SITE_DOWN", "raised_at"] - ti) <= pd.Timedelta(minutes=1)


def test_config_push(world: World, kpis: Kpis) -> None:
    for sc in scenarios(world, "config_push"):
        sites = affected_sites(sc)
        t0, t1 = sc["start_at"], sc["end_at"]
        assert pd.Timedelta(hours=4) <= t1 - t0 <= pd.Timedelta(hours=24)
        assert kpis.ratio("drop_rate_pct", sites, t0, t1) > 2.5
        cur, base = kpis.vs_baseline("rrc_success_pct", sites, t0, t1)
        assert base - cur > 2.5
        assert kpis.ratio("dl_volume_mb", sites, t0, t1) < 0.95
        changes = world.changes.set_index("change_id").loc[
            [e["id"] for e in sc["evidence"] if e["table"] == "changes"]
        ]
        pushes = changes[changes["status"] == "rolled_back"]
        rollbacks = changes[changes["change_type"] == "rollback"]
        assert len(pushes) == len(rollbacks) >= 1
        assert set(rollbacks["rollback_of"]) == set(pushes.index)
        assert (pushes["executed_at"] == t0).all()
        alarms = world.alarms.set_index("alarm_id").loc[
            [e["id"] for e in sc["evidence"] if e["table"] == "alarms"]
        ]
        assert alarms["severity"].isin(["minor", "warning"]).all()


def test_dns_degradation(world: World, kpis: Kpis) -> None:
    sites = all_sites(world)
    core = world.core_kpis.set_index(["node_id", "metric"]).sort_index()
    for sc in scenarios(world, "dns_degradation"):
        t0, t1 = sc["start_at"], sc["end_at"]
        assert pd.Timedelta(hours=1) <= t1 - t0 <= pd.Timedelta(hours=3)
        assert kpis.ratio("latency_ms", sites, t0, t1) > 1.25
        assert kpis.ratio("dl_volume_mb", sites, t0, t1) < 0.92
        cur, base = kpis.vs_baseline("rrc_success_pct", sites, t0, t1)
        assert abs(cur - base) < 0.3
        dns = core.loc[("CORE-DNS-01", "query_success_pct")].set_index("ts")["value"]
        assert dns[t0 + STEP : t1 - STEP].max() < 94
        assert dns[t0 - pd.Timedelta(hours=6) : t0 - STEP].min() > 99.5
        res = core.loc[("CORE-DNS-01", "resolution_ms")].set_index("ts")["value"]
        assert (
            res[t0 + STEP : t1 - STEP].min()
            > 4 * res[t0 - pd.Timedelta(hours=6) : t0 - STEP].median()
        )
        alarms = world.alarms.set_index("alarm_id").loc[[e["id"] for e in sc["evidence"]]]
        if sc["difficulty"] == "hard":
            assert alarms.empty
        else:
            assert (alarms["alarm_type"] == "DNS_TIMEOUT_RATE").all()
            assert (alarms["raised_at"] >= t0).all()


def test_dns_volume_effect(world: World, kpis: Kpis) -> None:
    """National DL volume falls 15-30 % against the same hours elsewhere."""
    total = kpis.arr["dl_volume_mb"].sum(axis=0)
    for sc in scenarios(world, "dns_degradation"):
        i0, i1 = kpis.idx(sc["start_at"]), kpis.idx(sc["end_at"])
        cur = total[i0:i1].sum()
        weekly = [
            total[i0 + 7 * k * STEPS_PER_DAY : i1 + 7 * k * STEPS_PER_DAY].sum()
            for k in range(-4, 5)
            if k and i0 + 7 * k * STEPS_PER_DAY >= 0 and i1 + 7 * k * STEPS_PER_DAY <= len(total)
        ]
        # Same-day contrast: the hour before and the hour after the incident.
        around = (total[i0 - 4 : i0].mean() + total[i1 : i1 + 4].mean()) / 2 * (i1 - i0)
        assert -0.35 < cur / around - 1 < -0.12, sc["scenario_id"]
        assert -0.35 < cur / np.median(weekly) - 1 < -0.08, sc["scenario_id"]


def test_congestion(world: World, kpis: Kpis) -> None:
    for sc in scenarios(world, "congestion"):
        sites = affected_sites(sc)
        t0, t1 = sc["start_at"], sc["end_at"]
        prb = kpis.series("prb_util_pct", sites, t0, t1)
        assert prb.max() >= 95
        assert (prb >= 90).mean() > 0.5  # saturated for most of the window
        assert kpis.ratio("latency_ms", sites, t0, t1) > 1.8
        assert kpis.ratio("drop_rate_pct", sites, t0, t1) > 1.5
        events = world.external_events
        near = events[(events["start_at"] < t1 + pd.Timedelta(hours=2)) & (events["end_at"] > t0)]
        assert near.empty  # no external event explains it
        alarms = world.alarms.set_index("alarm_id").loc[[e["id"] for e in sc["evidence"]]]
        assert (alarms["alarm_type"] == "HIGH_PRB").all()


def test_link_degradation(world: World, kpis: Kpis) -> None:
    links = world.nodes.set_index("node_id")
    for sc in scenarios(world, "link_degradation"):
        link = sc["root_cause_node_id"]
        assert links.loc[link, "attrs"]["medium"] == "microwave"
        sites = affected_sites(sc)
        t0, t1 = sc["start_at"], sc["end_at"]
        assert kpis.ratio("dl_volume_mb", sites, t0, t1) < 0.85
        assert kpis.ratio("latency_ms", sites, t0, t1) > 1.15
        assert kpis.series("availability_pct", sites, t0, t1).mean() > 95
        alarm = world.alarms.set_index("alarm_id").loc[sc["evidence"][0]["id"]]
        assert alarm["alarm_type"] == "LINK_DEGRADED" and alarm["severity"] == "major"
    # Harmless LINK_DEGRADED minor alarms exist elsewhere as noise.
    a = world.alarms
    assert ((a["alarm_type"] == "LINK_DEGRADED") & (a["severity"] == "minor")).sum() > 5


# ------------------------------------------------------------------------- red herrings


def test_planned_maintenance_matches_downtime(world: World, kpis: Kpis) -> None:
    mw = world.maintenance.set_index("mw_id")
    for sc in scenarios(world, "planned_maintenance"):
        row = mw.loc[next(e["id"] for e in sc["evidence"] if e["table"] == "maintenance")]
        assert row["status"] == "completed"
        assert row["node_id"] == sc["root_cause_node_id"]
        sites = affected_sites(sc) or [sc["root_cause_node_id"]]
        avail = kpis.arr["availability_pct"][kpis.rows(sites)].max(axis=0)
        near = np.zeros_like(avail, dtype=bool)
        near[kpis.idx(row["start_at"]) - 8 : kpis.idx(row["end_at"]) + 8] = True
        down_idx = np.flatnonzero((avail < 50) & near)
        first, last = kpis.ts[down_idx[0]], kpis.ts[down_idx[-1]]
        assert first + STEP > row["start_at"] and last < row["end_at"]
        assert (last + STEP - first) >= 0.8 * (row["end_at"] - row["start_at"])
        types = set(
            world.alarms.set_index("alarm_id").loc[
                [e["id"] for e in sc["evidence"] if e["table"] == "alarms"]
            ]["alarm_type"]
        )
        assert "SITE_DOWN" in types


def test_stadium_event_matches_spike(world: World, kpis: Kpis) -> None:
    ev = world.external_events.set_index("event_id")
    for sc in scenarios(world, "stadium_event"):
        row = ev.loc[next(e["id"] for e in sc["evidence"] if e["table"] == "external_events")]
        assert row["event_type"] == "stadium_event"
        assert pd.Timedelta(hours=3) <= row["end_at"] - row["start_at"] <= pd.Timedelta(hours=4)
        sites = affected_sites(sc)
        assert kpis.ratio("dl_volume_mb", sites, row["start_at"], row["end_at"]) > 1.6
        assert kpis.ratio("active_users", sites, row["start_at"], row["end_at"]) > 1.6
        assert kpis.vs_baseline("prb_util_pct", sites, row["start_at"], row["end_at"])[0] > 50
        series = kpis.arr["dl_volume_mb"][kpis.rows(sites)].sum(axis=0)
        day = slice(kpis.idx(row["start_at"]) - 24, kpis.idx(row["end_at"]) + 24)
        peak_ts = kpis.ts[day][int(np.argmax(series[day]))]
        assert row["start_at"] <= peak_ts <= row["end_at"] + STEP


def test_public_holiday(world: World, kpis: Kpis) -> None:
    (sc,) = scenarios(world, "public_holiday")
    ev = world.external_events.set_index("event_id").loc[sc["evidence"][0]["id"]]
    assert ev["event_type"] == "public_holiday" and pd.isna(ev["region_id"])
    total = kpis.arr["dl_volume_mb"].sum(axis=0)
    per_day = total.reshape(-1, STEPS_PER_DAY).sum(axis=1)
    d = kpis.idx(ev["start_at"]) // STEPS_PER_DAY
    same_weekday = [per_day[k] for k in range(len(per_day)) if k != d and (k - d) % 7 == 0]
    net = per_day[d] / np.median(same_weekday) - 1
    assert -0.25 < net < -0.08


def test_alarm_storm_has_no_kpi_impact(world: World, kpis: Kpis) -> None:
    for sc in scenarios(world, "alarm_storm"):
        site = sc["root_cause_node_id"]
        alarms = world.alarms.set_index("alarm_id").loc[[e["id"] for e in sc["evidence"]]]
        assert len(alarms) >= 20
        assert alarms["severity"].isin(["minor", "warning"]).all()
        assert (alarms["raised_at"].max() - alarms["raised_at"].min()) <= pd.Timedelta(hours=1)
        t0, t1 = sc["start_at"] - pd.Timedelta(hours=1), sc["end_at"] + pd.Timedelta(hours=1)
        assert 0.7 < kpis.ratio("dl_volume_mb", [site], t0, t1) < 1.4
        assert kpis.series("availability_pct", [site], t0, t1).min() > 85


# ------------------------------------------------------------------------ noise and questions


def test_background_noise_rates(world: World) -> None:
    a = world.alarms
    per_day = a.groupby(a["raised_at"].dt.floor("D")).size()
    assert 10 <= a.shape[0] / 30 <= 30
    assert per_day.max() < 70
    c = world.changes
    assert 1 <= c.shape[0] / 30 <= 3.5
    assert (c["change_type"] == "rollback").sum() > 0
    m = world.maintenance
    assert (m["status"] == "planned").any() and (m["status"] == "completed").sum() >= 6


FORBIDDEN = [
    "fiber", "fibre", "cable", "power", "mains", "battery", "dns", "config", "push",
    "rollback", "congest", "capacity", "maintenance", "stadium", "match", "holiday",
    "microwave", "link", "upgrade", "outage", "storm", "planned", "event", "concert",
]  # fmt: skip


def test_questions_do_not_leak(world: World) -> None:
    now = pd.Timestamp(
        dict(zip(world.dataset_meta["key"], world.dataset_meta["value"], strict=True))["now"]
    )
    for sc in world.scenarios.to_dict(orient="records"):
        qs = sc["questions"]
        assert 2 <= len(qs) <= 3
        assert len({q["text"] for q in qs}) == len(qs)
        allowed = set(sc["affected_node_ids"])
        if isinstance(sc["root_cause_node_id"], str) and sc["root_cause_node_id"].startswith("S-"):
            allowed.add(sc["root_cause_node_id"])
        for q in qs:
            low = q["text"].lower()
            assert not [w for w in FORBIDDEN if w in low], q["text"]
            for node in re.findall(r"\b(?:S|LNK|AGG|CORE)-[A-Z0-9-]+", q["text"]):
                assert node in allowed, (sc["scenario_id"], q["text"])
            asked = pd.Timestamp(q["asked_at"])
            assert sc["impact_start_at"] <= asked <= now


# -------------------------------------------------------------------------------- io


def test_io_round_trip(world: World, tmp_path: Path) -> None:
    write_world(world, tmp_path)
    again = read_world(tmp_path)
    for name, df in world.tables().items():
        pd.testing.assert_frame_equal(df, again.tables()[name], check_exact=True)
    gt = json.loads((tmp_path / "ground_truth.json").read_text(encoding="utf-8"))
    assert len(gt["scenarios"]) == len(world.scenarios)
    assert set(gt["scenarios"][0]) == {c for c, _ in SCHEMA["scenarios"]}
