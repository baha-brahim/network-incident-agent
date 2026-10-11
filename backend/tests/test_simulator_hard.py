"""Unit tests of the hard profile (no DB): every trap scenario is built as specified, can be told
apart from its decoy by the data, and leaves the default profile untouched."""

import re
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd
import pytest

from incident_agent.evals.scoring import trap_of
from incident_agent.simulator.build import build_world
from incident_agent.simulator.config import SimConfig, config_for_profile
from incident_agent.simulator.digest import world_digest
from incident_agent.simulator.hard.incidents import haversine_km
from incident_agent.simulator.world import SCHEMA, World
from tests.test_simulator import FORBIDDEN, STEP, Kpis, affected_sites

HARD_SEEDS = (101, 202)
TRAPS = {
    "change_on_root_node",
    "bad_change_loud_coincidence",
    "near_miss_maintenance",
    "congestion_on_match_day",
    "expected_event_looks_like_fault",
    "two_incidents_one_region",
    "missing_alarm",
    "maintenance_with_scary_change",
}
CHANGE_KEY = {
    "alarms": "alarm_id",
    "changes": "change_id",
    "maintenance": "mw_id",
    "external_events": "event_id",
}


@pytest.fixture(scope="module", params=HARD_SEEDS)
def hard(request: pytest.FixtureRequest) -> World:
    return build_world(request.param, profile="hard")


@pytest.fixture(scope="module")
def hkpis(hard: World) -> Kpis:
    return Kpis(hard)


class Index:
    """Row lookups and scenario selection on a world."""

    def __init__(self, w: World) -> None:
        self.w = w
        self.alarms = w.alarms.set_index("alarm_id")
        self.changes = w.changes.set_index("change_id")
        self.maint = w.maintenance.set_index("mw_id")
        self.events = w.external_events.set_index("event_id")
        self.nodes = w.nodes.set_index("node_id")
        self.scenarios = w.scenarios.to_dict(orient="records")

    def row(self, ref: dict[str, str]) -> pd.Series:
        table = {
            "alarms": self.alarms,
            "changes": self.changes,
            "maintenance": self.maint,
            "external_events": self.events,
        }[ref["table"]]
        row: pd.Series = table.loc[ref["id"]]
        return row

    def trap(self, trap: str) -> list[dict[str, Any]]:
        return [s for s in self.scenarios if trap_of(s["notes"]) == trap]

    def parent(self, node: str) -> str:
        return str(self.nodes.loc[node, "parent_id"])


@pytest.fixture(scope="module")
def ix(hard: World) -> Index:
    return Index(hard)


# ------------------------------------------------------------------------- the profile itself


def test_default_profile_is_the_plain_config() -> None:
    assert config_for_profile("default") == SimConfig()
    assert config_for_profile("default").profile == "default"
    assert config_for_profile("hard").profile == "hard"
    with pytest.raises(ValueError):
        config_for_profile("nightmare")


def test_default_world_has_no_profile_key(world_default: World) -> None:
    assert "profile" not in set(world_default.dataset_meta["key"])
    assert not any(trap_of(n) for n in world_default.scenarios["notes"])


@pytest.fixture(scope="module")
def world_default() -> World:
    return build_world(seed=7)


def test_hard_world_records_its_profile(hard: World) -> None:
    meta = dict(zip(hard.dataset_meta["key"], hard.dataset_meta["value"], strict=True))
    assert meta["profile"] == "hard"


def test_hard_world_is_deterministic(hard: World) -> None:
    seed = int(dict(zip(hard.dataset_meta["key"], hard.dataset_meta["value"], strict=True))["seed"])
    assert world_digest(build_world(seed, profile="hard")) == world_digest(hard)


def test_hard_seeds_differ() -> None:
    a, b = (build_world(s, profile="hard") for s in HARD_SEEDS)
    assert world_digest(a) != world_digest(b)
    assert not a.scenarios["start_at"].equals(b.scenarios["start_at"])


def test_hard_profile_differs_from_default_of_the_same_seed(hard: World) -> None:
    seed = int(dict(zip(hard.dataset_meta["key"], hard.dataset_meta["value"], strict=True))["seed"])
    assert world_digest(build_world(seed)) != world_digest(hard)


# ----------------------------------------------------------------------------- data contract


def test_hard_world_keeps_the_data_contract(hard: World) -> None:
    hard.validate()
    assert set(hard.tables()) == set(SCHEMA)
    assert len(hard.cell_kpis) == len(hard.cells) * 2880
    assert list(hard.scenarios.columns) == [c for c, _ in SCHEMA["scenarios"]]


def test_hard_world_has_no_nan_where_the_default_has_none(hard: World) -> None:
    c = hard.cell_kpis
    quality = ["rrc_success_pct", "drop_rate_pct", "latency_ms"]
    down = (c["availability_pct"] == 0).to_numpy()
    assert down.any()
    for col in quality:
        assert (c[col].isna().to_numpy() == down).all(), col
    others = [col for col, _ in SCHEMA["cell_kpis"] if col not in (*quality, "ts", "cell_id")]
    assert np.isfinite(c[others].to_numpy()).all()
    assert np.isfinite(hard.core_kpis["value"].to_numpy()).all()


def test_hard_evidence_and_foreign_keys(hard: World, ix: Index) -> None:
    nodes = set(hard.nodes["node_id"])
    known_tools = {
        "query_kpis",
        "get_topology",
        "get_alarms",
        "get_changes",
        "get_maintenance",
        "get_external_events",
        "get_anomalies",
        "search_runbooks",
    }
    assert hard.scenarios["scenario_id"].is_unique
    assert hard.scenarios["start_at"].is_monotonic_increasing
    for sc in ix.scenarios:
        for ref in [*sc["evidence"], *sc["confounders"]]:
            assert ref["id"] in set(getattr(hard, ref["table"])[CHANGE_KEY[ref["table"]]]), sc
        if isinstance(sc["root_cause_node_id"], str):
            assert sc["root_cause_node_id"] in nodes
        assert set(sc["affected_node_ids"]) <= nodes
        assert sc["expected_tools"] and set(sc["expected_tools"]) <= known_tools
        assert sc["start_at"] <= sc["impact_start_at"] <= sc["end_at"]
        evidence_ids = {e["id"] for e in sc["evidence"]}
        assert not evidence_ids & {c["id"] for c in sc["confounders"]}, sc["scenario_id"]
    changes = hard.changes
    assert set(changes.loc[changes["rollback_of"].notna(), "rollback_of"]) <= set(
        changes["change_id"]
    )


def test_hard_questions_do_not_leak(hard: World) -> None:
    now = pd.Timestamp(
        dict(zip(hard.dataset_meta["key"], hard.dataset_meta["value"], strict=True))["now"]
    )
    for sc in hard.scenarios.to_dict(orient="records"):
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
            assert sc["impact_start_at"] <= pd.Timestamp(q["asked_at"]) <= now


# ------------------------------------------------------------------------------ the mix


def test_hard_mix_covers_every_trap(hard: World) -> None:
    sc = hard.scenarios
    traps = Counter(trap_of(n) for n in sc["notes"])
    assert 30 <= len(sc) <= 40
    assert set(traps) >= TRAPS
    for trap in (
        "change_on_root_node",
        "bad_change_loud_coincidence",
        "near_miss_maintenance",
        "two_incidents_one_region",
    ):
        assert traps[trap] >= 3, trap
    assert traps[None] >= 3  # plain scenarios
    for row in sc.to_dict(orient="records"):
        if trap_of(row["notes"]):
            assert row["difficulty"] == "hard"
            assert re.match(r"^trap=[a-z0-9_]+; ", row["notes"])
            assert "Trap: " in row["notes"] and "Settled by: " in row["notes"]
        else:
            assert row["difficulty"] in ("easy", "medium")


def test_every_trap_decoy_is_listed_with_a_reason(ix: Index) -> None:
    for sc in ix.scenarios:
        if trap_of(sc["notes"]) not in (None, "missing_alarm"):
            assert sc["confounders"], sc["scenario_id"]
            assert all(c["why"] for c in sc["confounders"])
        elif trap_of(sc["notes"]) is None:
            assert not sc["confounders"]


# --------------------------------------------------------------------- 1. change on the root


def test_change_on_the_root_node(hard: World, hkpis: Kpis, ix: Index) -> None:
    found = ix.trap("change_on_root_node")
    kinds = {s["kind"] for s in found}
    assert {"dns_degradation", "power_outage", "fiber_cut", "congestion"} <= kinds
    for sc in found:
        (decoy,) = sc["confounders"]
        assert decoy["table"] == "changes"
        change = ix.changes.loc[decoy["id"]]
        root = sc["root_cause_node_id"]
        lead = sc["start_at"] - change["executed_at"]
        assert pd.Timedelta(minutes=20) <= lead <= pd.Timedelta(minutes=90), sc["scenario_id"]
        if sc["kind"] == "fiber_cut" or sc["kind"] == "link_degradation":
            assert change["node_id"] == ix.parent(root)  # the router above the link
            siblings = [
                n
                for n in ix.nodes.index
                if ix.nodes.loc[n, "node_type"] == "transport_link"
                and ix.nodes.loc[n, "parent_id"] == change["node_id"]
                and n != root
            ]
            assert siblings
            sib_sites = [n for n in ix.nodes.index if ix.nodes.loc[n, "parent_id"] in siblings]
            assert (
                hkpis.series("availability_pct", sib_sites, sc["start_at"], sc["end_at"]).min() > 85
            )
        else:
            assert change["node_id"] == root  # the failed node itself
        # No effect between the change and the onset, at the nodes the change touched.
        if sc["kind"] == "dns_degradation":
            core = hard.core_kpis.set_index(["node_id", "metric"]).sort_index()
            dns = core.loc[("CORE-DNS-01", "query_success_pct")].set_index("ts")["value"]
            assert dns[change["executed_at"] : sc["start_at"] - STEP].min() > 99.5
            # The same patch, same ticket, on other core nodes that stayed healthy.
            controls = ix.changes[
                (ix.changes["ticket"] == change["ticket"]) & (ix.changes.index != decoy["id"])
            ]
            assert len(controls) == 2 and not controls["node_id"].eq("CORE-DNS-01").any()
        elif sc["kind"] in ("power_outage", "congestion"):
            controls = ix.changes[
                (ix.changes["ticket"] == change["ticket"]) & (ix.changes.index != decoy["id"])
            ]
            assert len(controls) >= 1
            ctrl_sites = controls["node_id"].tolist()
            assert (
                hkpis.series("availability_pct", ctrl_sites, sc["start_at"], sc["end_at"]).min()
                > 85
            )
            if sc["kind"] == "congestion":
                assert (
                    hkpis.series("prb_util_pct", ctrl_sites, sc["start_at"], sc["end_at"]).max()
                    < 90
                )
        if sc["kind"] == "power_outage":
            site = root
            before = hkpis.series(
                "availability_pct", [site], change["executed_at"], sc["impact_start_at"] - STEP
            )
            assert before.min() > 85  # normal for hours after the change


def test_the_silent_dns_variant_has_no_alarm_and_the_other_one_has(ix: Index) -> None:
    dns = [s for s in ix.trap("change_on_root_node") if s["kind"] == "dns_degradation"]
    alarms = [[e for e in s["evidence"] if e["table"] == "alarms"] for s in dns]
    assert sorted(len(a) for a in alarms) == [0, 1]


# --------------------------------------------------------------------- 2. loud coincidence


def test_bad_change_with_a_loud_coincidence(hard: World, hkpis: Kpis, ix: Index) -> None:
    found = ix.trap("bad_change_loud_coincidence")
    assert {c["table"] for s in found for c in s["confounders"]} == {
        "maintenance",
        "alarms",
        "external_events",
    }
    for sc in found:
        sites = affected_sites(sc)
        t0, t1 = sc["start_at"], sc["end_at"]
        assert hkpis.ratio("drop_rate_pct", sites, t0, t1) > 2.5
        cur, base = hkpis.vs_baseline("rrc_success_pct", sites, t0, t1)
        assert base - cur > 2.5
        assert hkpis.series("availability_pct", sites, t0, t1).min() > 85
        changes = ix.changes.loc[[e["id"] for e in sc["evidence"] if e["table"] == "changes"]]
        pushes = changes[changes["status"] == "rolled_back"]
        rollbacks = changes[changes["change_type"] == "rollback"]
        assert len(pushes) == len(rollbacks) >= 1
        assert (pushes["executed_at"] == t0).all()
        assert (
            (rollbacks["executed_at"] - t1).between(pd.Timedelta(0), pd.Timedelta(minutes=4)).all()
        )
        loud = [ix.row(c) for c in sc["confounders"]]
        for c, row in zip(sc["confounders"], loud, strict=True):
            if c["table"] == "maintenance":
                other = row["node_id"]
                assert other not in sc["affected_node_ids"]
                osites = [n for n in ix.nodes.index if ix.nodes.loc[n, "parent_id"] == other]
                # The louder outage is on another link, and it opens after the regression began.
                assert row["start_at"] > t0 and row["end_at"] < t1
                assert (
                    hkpis.series(
                        "availability_pct",
                        osites,
                        row["start_at"] + STEP * 2,
                        row["end_at"] - STEP * 2,
                    ).max()
                    == 0
                )
            if c["table"] == "alarms" and row["alarm_type"] == "LINK_DEGRADED":
                # A major alarm on the parent of the pushed sites that clears by itself.
                assert row["severity"] == "major"
                assert row["node_id"] == ix.parent(sc["root_cause_node_id"])
                assert row["cleared_at"] - row["raised_at"] < pd.Timedelta(minutes=20)
            if c["table"] == "alarms" and row["alarm_type"] == "HIGH_PRB":
                assert ix.nodes.loc[row["node_id"], "attrs"]["near_venue"]
            if c["table"] == "external_events":
                assert row["event_type"] == "stadium_event" and row["end_at"] < t1
                assert not set(sites) & set(
                    ix.nodes[ix.nodes["attrs"].map(lambda a: a.get("near_venue", False))].index
                )


# ------------------------------------------------------------------------- 3. near misses


def test_near_miss_maintenance(hard: World, hkpis: Kpis, ix: Index) -> None:
    found = ix.trap("near_miss_maintenance")
    assert len(found) == 5
    shapes: set[str] = set()
    for sc in found:
        assert sc["is_incident"] and sc["root_cause_category"] in (
            "transport_failure",
            "power_failure",
        )
        t0, t1, root = sc["start_at"], sc["end_at"], sc["root_cause_node_id"]
        mw = [ix.row(c) for c in sc["confounders"] if c["table"] == "maintenance"]
        assert len(mw) == 1
        row = mw[0]
        sites = affected_sites(sc) or [root]
        down_from = sc["impact_start_at"]
        down = hkpis.series("availability_pct", sites, down_from + STEP, t1 - STEP)
        assert down.max() == 0
        if row["node_id"] != root:
            shapes.add("other_link")
            assert row["node_id"] not in sc["affected_node_ids"]
            assert ix.parent(row["node_id"]) == ix.parent(root)
        elif "None expected" in row["expected_impact"]:
            shapes.add("none_expected")
            assert row["start_at"] <= down_from and row["end_at"] >= t1  # covers it in time
        elif row["start_at"] > t0 + pd.Timedelta(minutes=45):
            shapes.add("starts_before")
            assert row["end_at"] >= t1 - pd.Timedelta(minutes=6)
            assert row["start_at"] - t0 >= pd.Timedelta(minutes=60)
            assert (
                hkpis.series("availability_pct", sites, t0 + STEP, row["start_at"] - STEP).max()
                == 0
            )
        else:
            shapes.add("overrun")
            assert t1 - row["end_at"] >= pd.Timedelta(minutes=120)
            assert row["start_at"] <= t0 <= row["start_at"] + pd.Timedelta(minutes=10)
            assert (
                hkpis.series("availability_pct", sites, row["end_at"] + STEP, t1 - STEP).max() == 0
            )
    assert shapes == {"other_link", "none_expected", "starts_before", "overrun"}


def test_near_miss_notes_say_which_part_is_outside_the_window(ix: Index) -> None:
    notes = [s["notes"] for s in ix.trap("near_miss_maintenance")]
    assert any("outside it" in n for n in notes)
    assert any("min after it closed" in n for n in notes)


# -------------------------------------------------------------------- 4. match-day congestion


def test_congestion_on_a_match_day(hard: World, hkpis: Kpis, ix: Index) -> None:
    found = ix.trap("congestion_on_match_day")
    assert len(found) >= 2
    venue = ix.nodes[ix.nodes["attrs"].map(lambda a: a.get("near_venue", False))]
    for sc in found:
        (site,) = affected_sites(sc)
        t0, t1 = sc["start_at"], sc["end_at"]
        assert site not in venue.index
        a = ix.nodes.loc[site, "attrs"]
        km = min(haversine_km(a["lat"], a["lon"], v["lat"], v["lon"]) for v in venue["attrs"])
        assert km >= 5.5
        assert ix.parent(site) not in set(venue["parent_id"])
        prb = hkpis.series("prb_util_pct", [site], t0, t1)
        assert prb.max() >= 95 and (prb >= 90).mean() > 0.5
        assert hkpis.ratio("latency_ms", [site], t0, t1) > 1.8
        events = [ix.row(c) for c in sc["confounders"] if c["table"] == "external_events"]
        assert len(events) == 1
        ev = events[0]
        assert ev["event_type"] == "stadium_event" and ev["region_id"] == "TUN"
        assert ev["start_at"] < t1 and ev["end_at"] > t0  # on the calendar at the same time
        # The match is real: the venue sites surge.
        vs = venue.index.tolist()
        assert hkpis.ratio("active_users", vs, ev["start_at"], ev["end_at"]) > 1.6
        assert "get_external_events" in sc["expected_tools"]


# ---------------------------------------------------------------- 5. event that looks faulty


def test_expected_event_with_scary_alarms(hard: World, hkpis: Kpis, ix: Index) -> None:
    found = ix.trap("expected_event_looks_like_fault")
    assert len(found) >= 2
    for sc in found:
        assert not sc["is_incident"] and sc["root_cause_category"] == "expected_event"
        sites = affected_sites(sc)
        ev = ix.events.loc[next(e["id"] for e in sc["evidence"] if e["table"] == "external_events")]
        assert hkpis.ratio("active_users", sites, ev["start_at"], ev["end_at"]) > 1.6
        assert hkpis.series("availability_pct", sites, ev["start_at"], ev["end_at"]).min() > 85
        high = ix.alarms.loc[[e["id"] for e in sc["evidence"] if e["table"] == "alarms"]]
        assert (high["alarm_type"] == "HIGH_PRB").all() and set(high["node_id"]) == set(sites)
        majors = [ix.row(c) for c in sc["confounders"]]
        assert majors and all(r["severity"] == "major" for r in majors)
        assert all(r["cleared_at"] - r["raised_at"] < pd.Timedelta(minutes=20) for r in majors)
        assert all(ev["start_at"] < r["raised_at"] < ev["end_at"] for r in majors)


# ------------------------------------------------------------------- 6. two incidents at once


def test_two_incidents_in_one_region(hard: World, hkpis: Kpis, ix: Index) -> None:
    groups: dict[str, list[dict[str, Any]]] = {}
    for sc in ix.trap("two_incidents_one_region"):
        name = re.search(r"group '([^']+)'", sc["notes"])
        assert name
        groups.setdefault(name.group(1), []).append(sc)
    assert len(groups) >= 3
    for pair in groups.values():
        a, b = pair
        assert (
            a["affected_region_ids"] == b["affected_region_ids"]
            and len(a["affected_region_ids"]) == 1
        )
        assert not set(a["affected_node_ids"]) & set(b["affected_node_ids"])
        assert a["kind"] != b["kind"]
        overlap = min(a["end_at"], b["end_at"]) - max(a["impact_start_at"], b["impact_start_at"])
        assert overlap >= pd.Timedelta(minutes=45)
        for sc, other in ((a, b), (b, a)):
            sites = affected_sites(sc)
            mine = set(sc["affected_node_ids"])
            assert not any(n in other["affected_node_ids"] for n in mine)
            (decoy,) = sc["confounders"]
            assert ix.row(decoy) is not None
            for q in sc["questions"]:
                named = re.findall(r"\bS-[A-Z]+-\d+\b", q["text"])
                assert named and set(named) <= set(sites) | {sc["root_cause_node_id"]}
                assert not set(named) & set(other["affected_node_ids"])


# ------------------------------------------------------------------------- 7. missing alarm


def test_missing_alarms(hard: World, hkpis: Kpis, ix: Index) -> None:
    found = ix.trap("missing_alarm")
    assert {s["kind"] for s in found} == {"fiber_cut", "power_outage"}
    for sc in found:
        root, t0 = sc["root_cause_node_id"], sc["start_at"]
        window = ix.w.alarms[
            (ix.w.alarms["raised_at"] >= t0 - pd.Timedelta(hours=3))
            & (ix.w.alarms["raised_at"] <= sc["end_at"])
        ]
        if sc["kind"] == "fiber_cut":
            sites = affected_sites(sc)
            assert len(sites) >= 2
            assert (
                not (window["alarm_type"] == "LINK_LOS").any()
                or not (window.loc[window["alarm_type"] == "LINK_LOS", "node_id"] == root).any()
            )
            down = window[(window["alarm_type"] == "SITE_DOWN") & window["node_id"].isin(sites)]
            assert set(down["node_id"]) == set(sites)
            assert (ix.nodes.loc[sites, "parent_id"] == root).all()
            assert (
                hkpis.series("availability_pct", sites, t0 + STEP, sc["end_at"] - STEP).max() == 0
            )
        else:
            mine = window[window["node_id"] == root]
            assert "MAINS_FAILURE" not in set(mine["alarm_type"])
            assert {"BATTERY_LOW", "SITE_DOWN"} <= set(mine["alarm_type"])
            before = hkpis.series("availability_pct", [root], t0, sc["impact_start_at"] - STEP)
            assert before.min() > 85


# --------------------------------------------------------------- 8. maintenance with a change


def test_maintenance_with_a_scary_change(hard: World, hkpis: Kpis, ix: Index) -> None:
    found = ix.trap("maintenance_with_scary_change")
    assert len(found) >= 2
    for sc in found:
        assert not sc["is_incident"] and sc["root_cause_category"] == "planned_maintenance"
        mw = ix.maint.loc[next(e["id"] for e in sc["evidence"] if e["table"] == "maintenance")]
        assert mw["status"] == "completed" and mw["node_id"] == sc["root_cause_node_id"]
        (decoy,) = sc["confounders"]
        change = ix.changes.loc[decoy["id"]]
        assert change["node_id"] == mw["node_id"]
        assert (
            pd.Timedelta(minutes=15)
            <= mw["start_at"] - change["executed_at"]
            <= pd.Timedelta(minutes=65)
        )
        sites = affected_sites(sc) or [mw["node_id"]]
        avail = hkpis.series(
            "availability_pct", sites, change["executed_at"], mw["start_at"] - STEP
        )
        assert avail.min() > 85  # nothing happens between the change and the window
        inside = hkpis.series(
            "availability_pct", sites, mw["start_at"] + STEP * 2, mw["end_at"] - STEP * 2
        )
        assert inside.max() == 0


# -------------------------------------------------------------------------- plain scenarios


def test_plain_scenarios_are_default_style(ix: Index) -> None:
    plain = [s for s in ix.scenarios if trap_of(s["notes"]) is None]
    assert {s["kind"] for s in plain} >= {"fiber_cut", "config_push", "public_holiday"}
    assert all(not s["notes"].startswith("trap=") for s in plain)


def test_hard_world_scenarios_do_not_overlap_except_pairs(ix: Index) -> None:
    rows = ix.scenarios
    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            if a["start_at"] < b["end_at"] and b["start_at"] < a["end_at"]:
                assert trap_of(a["notes"]) == trap_of(b["notes"]) == "two_incidents_one_region"


# ---------------------------------------------------------------------------------- detector


def test_the_detector_runs_unchanged_on_a_hard_world() -> None:
    from incident_agent.detector.config import DetectorConfig
    from incident_agent.detector.evaluate import evaluate_prepared, prepare_world

    cfg = DetectorConfig()
    world = build_world(101, profile="hard")
    evaluation = evaluate_prepared(prepare_world(world, 101, cfg), cfg)
    assert evaluation.n_alerts > 0
    assert evaluation.n_detectable >= 30
    assert evaluation.recall >= 0.9
