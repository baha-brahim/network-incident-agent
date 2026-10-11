"""Tool tests against the fixture world in the test database (`docker compose up -d`)."""

from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from incident_agent.agent.tools import execute_tool
from incident_agent.agent.tools.common import BODY_CHARS
from incident_agent.agent.tools.timeutil import fmt, iso
from incident_agent.agent.types import ToolContext, ToolResult
from incident_agent.db.loader import load_world
from incident_agent.rag import HashEmbedder
from incident_agent.rag.ingest import ingest
from tests.fixtures_world import NOW, at, make_fixture_world

pytestmark = pytest.mark.db

EMB = HashEmbedder()

# Fixture timeline (local Africa/Tunis; day 0 is Tuesday 2026-09-01):
#   fiber cut LNK-TUN-01-A  day1 18:00-22:00   alarms ALM-000001 (link), ALM-000002 (S-TUN-001)
#   DNS degraded            day1 12:00-14:00   alarm ALM-000003 raised 12:30, never cleared
#   config push AGG-TUN-01  day0 10:00, rolled back day0 16:00 (CHG-2026-0002 / -0003)
#   maintenance S-SFX-001   day2 03:00-05:00   MW-0001
#   stadium event TUN       day2 19:00-22:00   EVT-001
#   SFX blackout            day3 01:00-02:00   (not a scenario: regional quality KPIs are NULL)

Call = Callable[..., ToolResult]


@pytest.fixture(scope="module")
def world(db_engine: Engine) -> Iterator[Engine]:
    load_world(make_fixture_world(), db_engine)
    ingest(engine=db_engine, embedder=EMB)
    _insert_detector_rows(db_engine)
    yield db_engine
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM anomalies WHERE anomaly_id LIKE 'ANM-T%'"))
        conn.execute(text("DELETE FROM alerts WHERE alert_id LIKE 'ALR-T%'"))


def _insert_detector_rows(engine: Engine) -> None:
    alerts = [
        # finished fiber-cut alert on day 1
        ("ALR-T1", at(1, 18), at(1, 21.75), ["TUN"], ["S-TUN-001", "S-TUN-002", "TUN"],
         ["availability_pct", "dl_volume_mb"], "high", 12.5, 3,
         "Traffic and availability drop on 2 sites in TUN (S-TUN-001, S-TUN-002) for 4 h"),
        # alert in SFX on day 3 (blackout), ends at 01:45
        ("ALR-T3", at(3, 1), at(3, 1.75), ["SFX"], ["S-SFX-001", "SFX"],
         ["availability_pct"], "medium", 9.5, 1,
         "Availability drops on 1 site in SFX (S-SFX-001) for 1 h"),
    ]  # fmt: skip
    anomalies = [
        ("ANM-T1", "ALR-T1", "site", "S-TUN-001", "TUN", "availability_pct", "drop",
         at(1, 18), at(1, 21.75), 16, -60.0, 100.0, 0.0),
        ("ANM-T2", "ALR-T1", "site", "S-TUN-002", "TUN", "availability_pct", "drop",
         at(1, 18), at(1, 21.75), 16, -55.0, 100.0, 0.0),
        ("ANM-T3", "ALR-T1", "site", "S-TUN-001", "TUN", "dl_volume_mb", "drop",
         at(1, 18), at(1, 21.75), 16, -20.0, 9000.0, 0.0),
        ("ANM-T5", "ALR-T3", "site", "S-SFX-001", "SFX", "availability_pct", "drop",
         at(3, 1), at(3, 1.75), 4, -50.0, 100.0, 0.0),
    ]  # fmt: skip
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM anomalies"))
        conn.execute(text("DELETE FROM alerts"))
        for a in alerts:
            conn.execute(
                text(
                    "INSERT INTO alerts (alert_id, start_at, end_at, region_ids, entity_ids, "
                    "metrics, severity, score, n_anomalies, summary) VALUES (:id, :s, :e, :r, "
                    ":ent, :m, :sev, :sc, :n, :sum)"
                ),
                dict(
                    zip(("id", "s", "e", "r", "ent", "m", "sev", "sc", "n", "sum"), a, strict=True)
                ),
            )
        for n in anomalies:
            conn.execute(
                text(
                    "INSERT INTO anomalies (anomaly_id, alert_id, entity_type, entity_id, "
                    "region_id, metric, direction, start_at, end_at, n_steps, peak_z, "
                    "baseline_value, observed_value) VALUES (:a, :al, :et, :ei, :r, :m, :d, "
                    ":s, :e, :n, :z, :b, :o)"
                ),
                dict(
                    zip(
                        ("a", "al", "et", "ei", "r", "m", "d", "s", "e", "n", "z", "b", "o"),
                        n,
                        strict=True,
                    )
                ),
            )


@pytest.fixture
def call(world: Engine, agent_ro_engine: Engine) -> Call:
    def _call(name: str, args: dict[str, Any], asked_at: datetime = NOW) -> ToolResult:
        ctx = ToolContext(engine=agent_ro_engine, asked_at=asked_at, embedder=EMB)
        return execute_tool(name, args, ctx)

    return _call


def span(start: datetime, end: datetime) -> dict[str, str]:
    return {"start": start.isoformat(), "end": end.isoformat()}


FULL = span(at(0, 0), at(3, 8))


# --- topology ---------------------------------------------------------------------------------


def test_topology_of_a_site_shows_chain_cells_and_siblings(call: Call) -> None:
    r = call("get_topology", {"node_id": "S-TUN-001"})
    assert not r.error
    assert "S-TUN-001 (site) -> LNK-TUN-01-A (fiber link) -> AGG-TUN-01 (agg router)" in r.body
    assert "CORE-UPF-01" in r.body
    assert "Siblings under LNK-TUN-01-A: S-TUN-002" in r.body
    assert "C-TUN-001-1" in r.body and "CORE-DNS-01" in r.body  # cells and shared services
    refs = {ref.ref for ref in r.refs}
    assert {"S-TUN-001", "LNK-TUN-01-A", "AGG-TUN-01", "CORE-UPF-01", "S-TUN-002"} <= refs
    assert all(ref.kind == "node" for ref in r.refs)


def test_topology_of_a_link_lists_the_sites_that_fail_with_it(call: Call) -> None:
    r = call("get_topology", {"node_id": "LNK-TUN-01-A"})
    assert "Sites below: S-TUN-001, S-TUN-002" in r.body
    assert "takes down all 2 of them together" in r.body
    assert "Siblings under AGG-TUN-01: LNK-TUN-01-B" in r.body


def test_topology_of_a_router_counts_all_sites_below(call: Call) -> None:
    r = call("get_topology", {"node_id": "AGG-TUN-01"})
    assert "Children: LNK-TUN-01-A, LNK-TUN-01-B" in r.body
    assert "3 sites in total depend on AGG-TUN-01" in r.body
    assert r.data["sites_below"] == 3


def test_topology_include_filters(call: Call) -> None:
    only_up = call("get_topology", {"node_id": "S-TUN-001", "include": "ancestors"})
    assert "Siblings" not in only_up.body and "Depends on" in only_up.body
    only_down = call("get_topology", {"node_id": "AGG-TUN-01", "include": "descendants"})
    assert "Depends on" not in only_down.body and "Children" in only_down.body


def test_topology_accepts_a_cell_id_and_a_region_id(call: Call) -> None:
    r = call("get_topology", {"node_id": "C-TUN-001-2"})
    assert "is a cell of S-TUN-001" in r.body and "LNK-TUN-01-A" in r.body
    region = call("get_topology", {"node_id": "SFX"})
    assert not region.error and "region" in region.body and "AGG-SFX-01" in region.body


def test_topology_unknown_node_suggests_a_fix(call: Call) -> None:
    r = call("get_topology", {"node_id": "S-TUN-01"})
    assert r.error and "S-TUN-001" in r.error


# --- alarms -----------------------------------------------------------------------------------


def test_alarms_fiber_cut_leads_with_the_cause(call: Call) -> None:
    r = call("get_alarms", {**span(at(1, 17), at(1, 23)), "node_ids": ["LNK-TUN-01-A"]})
    lines = r.body.splitlines()
    assert "Earliest critical/major" in lines[1] and "LINK_LOS on LNK-TUN-01-A" in lines[1]
    assert "within 10 min after: SITE_DOWN x1 (S-TUN-001)" in lines[1]
    assert "ALM-000001" in r.body and "ALM-000002 critical SITE_DOWN S-TUN-001 (below" in r.body
    assert {ref.ref for ref in r.refs} == {"ALM-000001", "ALM-000002"}
    assert all(ref.kind == "alarm" for ref in r.refs)
    assert [row["alarm_id"] for row in r.data["rows"]] == ["ALM-000001", "ALM-000002"]


def test_alarms_headline_has_the_counts_and_the_earliest_serious_alarm(call: Call) -> None:
    r = call("get_alarms", {**span(at(1, 17), at(1, 23)), "node_ids": ["LNK-TUN-01-A"]})
    assert r.headline == r.body.splitlines()[0] and len(r.headline) <= 200
    assert r.headline.startswith(
        "2 alarm(s) on LNK-TUN-01-A and nodes below: 2 critical; 0 active."
    )
    assert r.headline.endswith(
        f"Earliest critical/major: {fmt(at(1, 18))} LINK_LOS on LNK-TUN-01-A (ALM-000001)."
    )
    dns = call("get_alarms", {**span(at(1, 12), at(1, 15)), "node_ids": ["CORE-DNS-01"]})
    assert dns.headline.startswith("1 alarm(s) on CORE-DNS-01 and nodes below: 1 major; 1 active.")
    assert "DNS_TIMEOUT_RATE on CORE-DNS-01 (ALM-000003)" in dns.headline
    assert call(
        "get_alarms", {**span(at(1, 17), at(1, 23)), "node_ids": ["S-TUN-003"]}
    ).headline.startswith("No alarms on S-TUN-003")


def test_alarms_not_cleared_at_asked_at_are_active_and_hide_their_clear_time(call: Call) -> None:
    asked = at(1, 20)
    r = call("get_alarms", {**span(at(1, 17), at(1, 23)), "node_ids": ["LNK-TUN-01-A"]}, asked)
    assert "Window cut at asked_at" in r.body
    assert r.body.count(": active") == 2 and "cleared" not in r.body
    assert fmt(at(1, 22)) not in r.body and iso(at(1, 22)) not in str(r.data)
    assert all(row["active"] and row["cleared_at"] is None for row in r.data["rows"])
    assert all("active" in ref.summary and "cleared" not in ref.summary for ref in r.refs)
    after = call("get_alarms", {**span(at(1, 17), at(1, 23)), "node_ids": ["LNK-TUN-01-A"]})
    assert f"cleared {fmt(at(1, 22))}" in after.body and ": active" not in after.body


def test_alarms_raised_after_asked_at_are_invisible(call: Call) -> None:
    r = call("get_alarms", span(at(1, 17), at(1, 23)), at(1, 17.5))
    assert "ALM-000001" not in r.body and "ALM-000002" not in r.body
    assert "ALM-000003" in r.body  # the DNS alarm (12:30) was already active
    exact = call(
        "get_alarms", {**span(at(1, 17), at(1, 23)), "node_ids": ["LNK-TUN-01-A"]}, at(1, 18)
    )
    assert "ALM-000001" in exact.body  # raised exactly at asked_at is visible
    assert "ALM-000002" not in exact.body  # raised a minute later is not


def test_alarm_raised_before_the_window_but_still_active_is_listed(call: Call) -> None:
    r = call("get_alarms", {**span(at(1, 19), at(1, 20)), "node_ids": ["S-TUN-001"]})
    assert "ALM-000002" in r.body


def test_alarms_window_entirely_after_asked_at(call: Call) -> None:
    r = call("get_alarms", span(at(2, 0), at(2, 5)), at(1, 12))
    assert not r.error and "nothing is visible" in r.body and not r.refs


def test_alarms_include_descendants_flag(call: Call) -> None:
    window = span(at(1, 17), at(1, 23))
    on = call("get_alarms", {**window, "node_ids": ["LNK-TUN-01-A"], "include_descendants": True})
    off = call("get_alarms", {**window, "node_ids": ["LNK-TUN-01-A"], "include_descendants": False})
    assert "ALM-000002" in on.body and "ALM-000002" not in off.body and "ALM-000001" in off.body
    up = call("get_alarms", {**window, "node_ids": ["S-TUN-001"]})
    assert "ALM-000002" in up.body and "ALM-000001" not in up.body  # the link is above, not below


def test_alarms_region_scope_includes_core_nodes(call: Call) -> None:
    r = call("get_alarms", {**span(at(1, 10), at(1, 23)), "region_id": "tun"})
    assert "ALM-000003" in r.body and "ALM-000001" in r.body
    sfx = call("get_alarms", {**span(at(1, 10), at(1, 23)), "region_id": "SFX"})
    assert "ALM-000003" in sfx.body and "ALM-000001" not in sfx.body


def test_alarms_filters(call: Call) -> None:
    window = span(at(1, 10), at(1, 23))
    r = call("get_alarms", {**window, "alarm_types": ["dns_timeout_rate"]})
    assert "ALM-000003" in r.body and "ALM-000001" not in r.body
    r = call("get_alarms", {**window, "min_severity": "critical"})
    assert "ALM-000003" not in r.body and "ALM-000001" in r.body


def test_alarms_never_cleared_stay_active_forever(call: Call) -> None:
    r = call("get_alarms", {**span(at(3, 0), at(3, 8)), "node_ids": ["CORE-DNS-01"]})
    assert "ALM-000003" in r.body and "active" in r.body


def test_alarms_bad_scope_gives_helpful_errors(call: Call) -> None:
    r = call("get_alarms", {**FULL, "node_ids": ["S-TUN-01"]})
    assert r.error and "S-TUN-001" in r.error
    r = call("get_alarms", {**FULL, "region_id": "XXX"})
    assert r.error and "Regions: SFX, TUN" in r.error
    r = call("get_alarms", {"start": "not a date", "end": "2026-09-02"})
    assert r.error and "ISO 8601" in r.error
    mixed = call("get_alarms", {**FULL, "node_ids": ["S-TUN-001", "NOPE-1"]})
    assert not mixed.error and "Unknown node ids ignored" in mixed.body


def test_alarms_empty_result_says_where_it_looked(call: Call) -> None:
    r = call("get_alarms", {**span(at(0, 0), at(0, 6)), "node_ids": ["S-TUN-003"]})
    assert r.body.startswith("No alarms on S-TUN-003") and not r.error and not r.truncated


@pytest.fixture
def alarm_storm(world: Engine) -> Iterator[None]:
    rows = [
        (f"ALM-X{i:04d}", f"S-TUN-00{1 + i % 3}", "TEMP_HIGH", "warning", at(1, 10 + i / 100), None)
        for i in range(80)
    ] + [
        (f"ALM-X9{i:03d}", "S-SFX-001", "SITE_DOWN", "critical", at(1, 11.5 + i / 60), None)
        for i in range(3)
    ]
    with world.begin() as conn:
        for r in rows:
            conn.execute(
                text(
                    "INSERT INTO alarms (alarm_id, node_id, alarm_type, severity, raised_at, "
                    "cleared_at, description) VALUES (:a, :n, :t, :s, :r, :c, 'storm')"
                ),
                dict(zip("antsrc", r, strict=True)),
            )
    yield
    with world.begin() as conn:
        conn.execute(text("DELETE FROM alarms WHERE alarm_id LIKE 'ALM-X%'"))


def test_alarm_storm_is_grouped_and_keeps_the_serious_alarms_as_rows(
    call: Call, alarm_storm: None
) -> None:
    r = call("get_alarms", span(at(1, 9), at(1, 13)))
    assert len(r.body) <= BODY_CHARS and r.body.splitlines()[0].startswith("84 alarm")
    assert r.body.count("critical SITE_DOWN S-SFX-001") == 3  # serious ones stay individual
    assert "warning TEMP_HIGH S-TUN-001 x27 (e.g. ALM-X" in r.body  # the noise is folded
    assert "Earliest critical/major" in r.body.splitlines()[1]
    assert r.data["n_total"] == 84
    groups = [row for row in r.data["rows"] if row.get("group")]
    assert sum(g["count"] for g in groups) == 80 and all(len(g["alarm_ids"]) > 1 for g in groups)
    assert len(r.refs) == len(r.data["rows"]) and not r.truncated


@pytest.fixture
def alarm_scatter(world: Engine) -> Iterator[None]:
    nodes = ["S-TUN-001", "S-TUN-002", "S-TUN-003", "S-SFX-001", "S-SFX-002", "LNK-TUN-01-B"]
    rows = [
        (f"ALM-Y{i:04d}", node, f"NOISE_{k:02d}", "warning", at(1, 8 + i / 100), None)
        for i, (node, k) in enumerate((n, k) for n in nodes for k in range(30))
    ]
    with world.begin() as conn:
        for r in rows:
            conn.execute(
                text(
                    "INSERT INTO alarms (alarm_id, node_id, alarm_type, severity, raised_at, "
                    "cleared_at, description) VALUES (:a, :n, :t, :s, :r, :c, 'noise')"
                ),
                dict(zip("antsrc", r, strict=True)),
            )
    yield
    with world.begin() as conn:
        conn.execute(text("DELETE FROM alarms WHERE alarm_id LIKE 'ALM-Y%'"))


def test_too_many_distinct_alarms_are_truncated_to_the_budget(
    call: Call, alarm_scatter: None
) -> None:
    r = call("get_alarms", span(at(1, 7), at(1, 13)))
    assert r.truncated and len(r.body) <= BODY_CHARS
    assert "Omitted" in r.body and "NOISE_" in r.body and "ALM-000003" in r.body
    assert r.data["n_total"] == 181 and len(r.data["rows"]) < 181
    assert len(r.refs) == len(r.data["rows"])  # refs only for rows the model can see


def test_quiet_window_says_there_is_no_serious_alarm(call: Call, alarm_storm: None) -> None:
    r = call("get_alarms", {**span(at(1, 9), at(1, 11)), "min_severity": "warning"})
    assert "No critical or major alarm" in r.body


# --- changes ----------------------------------------------------------------------------------


def test_changes_rollback_after_asked_at_is_not_visible(call: Call) -> None:
    window = span(at(0, 0), at(1, 0))
    early = call("get_changes", window, at(0, 12))
    assert "CHG-2026-0002" in early.body and "CHG-2026-0003" not in early.body
    assert "ROLLED BACK" not in early.body and "in effect (not rolled back)" in early.body
    row = early.data["rows"][0]
    assert row["change_id"] == "CHG-2026-0002" and row["rolled_back"] is False
    assert "ROLLED BACK" not in early.refs[0].summary
    late = call("get_changes", window, at(0, 18))
    assert f"ROLLED BACK by CHG-2026-0003 at {fmt(at(0, 16))}" in late.body
    assert "rollback of CHG-2026-0002" in late.body
    assert {r.ref for r in late.refs} == {"CHG-2026-0002", "CHG-2026-0003"}


def test_changes_include_ancestors_flag(call: Call) -> None:
    window = span(at(0, 0), at(3, 8))
    on = call("get_changes", {**window, "node_ids": ["S-TUN-001"]})
    assert "CHG-2026-0002 config_push on AGG-TUN-01 (ancestor of S-TUN-001)" in on.body
    assert "CHG-2026-0001" not in on.body  # DNS is not in the parent chain
    off = call("get_changes", {**window, "node_ids": ["S-TUN-001"], "include_ancestors": False})
    assert off.body.startswith("No changes on S-TUN-001")
    core = call("get_changes", {**window, "region_id": "SFX"})
    assert "CHG-2026-0001" in core.body  # core nodes are upstream of every region


def test_changes_clamp_to_asked_at_and_to_the_window(call: Call) -> None:
    r = call("get_changes", span(at(0, 0), at(3, 8)), at(1, 10))
    assert "CHG-2026-0001" not in r.body  # executed at day1 11:00, after asked_at
    assert "Window cut at asked_at" in r.body
    narrow = call("get_changes", span(at(1, 10), at(1, 12)))
    assert "CHG-2026-0001" in narrow.body and "CHG-2026-0002" not in narrow.body


# --- maintenance ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("asked", "state"),
    [(at(2, 2), "planned"), (at(2, 4), "in progress"), (at(2, 6), "completed")],
)
def test_maintenance_state_is_relative_to_asked_at(call: Call, asked: datetime, state: str) -> None:
    r = call("get_maintenance", {**span(at(2, 0), at(2, 8)), "node_ids": ["S-SFX-001"]}, asked)
    assert "MW-0001" in r.body and state in r.body.lower()
    assert r.data["rows"][0]["state"] == state
    assert [ref.ref for ref in r.refs] == ["MW-0001"] and r.refs[0].kind == "maintenance"
    assert "battery swap" in r.body and "site down" in r.body


def test_future_maintenance_window_is_visible_like_a_calendar(call: Call) -> None:
    r = call("get_maintenance", span(at(2, 0), at(2, 8)), at(2, 2))
    assert "planned" in r.body and "starts in 60 min" in r.body
    assert "calendar entries that start after asked_at" in r.body


def test_maintenance_on_a_parent_covers_the_sites_below(call: Call, world: Engine) -> None:
    with world.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO maintenance VALUES ('MW-T001', 'LNK-TUN-01-A', :s, :e, "
                "'splicing', 'sites offline', 'planned')"
            ),
            {"s": at(2, 22), "e": at(2, 23)},
        )
    try:
        r = call("get_maintenance", {**span(at(2, 20), at(3, 0)), "node_ids": ["S-TUN-001"]})
        assert "MW-T001" in r.body and "(ancestor of S-TUN-001)" in r.body
        assert "covers 2 sites below" in r.body
        off = call(
            "get_maintenance",
            {**span(at(2, 20), at(3, 0)), "node_ids": ["S-TUN-001"], "include_ancestors": False},
        )
        assert "MW-T001" not in off.body
    finally:
        with world.begin() as conn:
            conn.execute(text("DELETE FROM maintenance WHERE mw_id = 'MW-T001'"))


def test_maintenance_empty_means_none_scheduled(call: Call) -> None:
    r = call("get_maintenance", {**span(at(0, 0), at(1, 0)), "node_ids": ["S-TUN-001"]})
    assert r.body.startswith("No maintenance window scheduled on S-TUN-001 and its parents")


def test_maintenance_region_filter(call: Call) -> None:
    assert "MW-0001" in call("get_maintenance", {**FULL, "region_id": "SFX"}).body
    assert "MW-0001" not in call("get_maintenance", {**FULL, "region_id": "TUN"}).body


# --- external events --------------------------------------------------------------------------


def test_event_in_progress_hides_its_end(call: Call) -> None:
    r = call("get_external_events", span(at(2, 0), at(2, 23)), at(2, 20))
    assert "EVT-001" in r.body and "in progress" in r.body
    assert fmt(at(2, 22)) not in r.body and r.data["rows"][0]["end_at"] is None
    assert "near S-TUN-003" in r.body and "Window cut" in r.body
    done = call("get_external_events", span(at(2, 0), at(2, 23)), at(2, 23))
    assert fmt(at(2, 22)) in done.body and done.data["rows"][0]["end_at"] is not None


def test_event_after_asked_at_is_invisible(call: Call) -> None:
    r = call("get_external_events", span(at(2, 0), at(2, 23)), at(2, 18))
    assert "No external events" in r.body and not r.refs


def test_event_region_filter(call: Call) -> None:
    assert "EVT-001" in call("get_external_events", {**FULL, "region_id": "TUN"}).body
    assert "No external events" in call("get_external_events", {**FULL, "region_id": "SFX"}).body
    assert call("get_external_events", {**FULL, "region_id": "ZZZ"}).error


def test_nationwide_event_is_included_in_every_region(call: Call, world: Engine) -> None:
    with world.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO external_events VALUES ('EVT-T01', NULL, NULL, 'public_holiday', "
                ":s, :e, 'National holiday')"
            ),
            {"s": at(3, 0), "e": at(3, 23)},
        )
    try:
        r = call("get_external_events", {**FULL, "region_id": "SFX"})
        assert "EVT-T01" in r.body and "nationwide" in r.body
    finally:
        with world.begin() as conn:
            conn.execute(text("DELETE FROM external_events WHERE event_id = 'EVT-T01'"))


# --- KPIs -------------------------------------------------------------------------------------

OUTAGE = {
    "entity_type": "site",
    "entity_ids": ["S-SFX-001"],
    "metrics": ["availability_pct", "dl_volume_mb"],
    **span(at(2, 0), at(2, 8)),
}


def test_kpis_onset_and_recovery_of_a_site_outage(call: Call) -> None:
    r = call("query_kpis", OUTAGE)
    assert not r.error
    assert r.body.startswith("Deviation in 2 of 2 series. Earliest onset " + fmt(at(2, 3)))
    assert f"recovery {fmt(at(2, 5))}" in r.body
    pair = next(p for p in r.data["pairs"] if p["metric"] == "availability_pct")
    assert pair["onset"] == iso(at(2, 3)) and pair["recovery"] == iso(at(2, 5))
    assert pair["direction"] == "below" and pair["ongoing"] is False
    assert pair["min"] == 0.0 and pair["baseline_mean"] == pytest.approx(100.0)
    assert len(pair["series"]) <= 12
    assert "Thin baseline: only 2 earlier weekdays" in r.body


def test_kpis_unrecovered_outage_at_asked_at_does_not_leak_the_recovery(call: Call) -> None:
    r = call("query_kpis", OUTAGE, at(2, 4))
    assert "Window cut at asked_at" in r.body and "not recovered" in r.body
    assert fmt(at(2, 5)) not in r.body and "recovery" not in r.body.lower().replace("recovered", "")
    for pair in r.data["pairs"]:
        assert pair["n_steps"] == 17 and pair["recovery"] is None and pair["ongoing"] is True
        assert pair["series_start"] == iso(at(2, 0))
    assert iso(at(2, 5)) not in str(r.data)


def test_kpis_before_the_outage_nothing_is_visible(call: Call) -> None:
    r = call("query_kpis", OUTAGE, at(2, 2))
    assert "No sustained" in r.body or "No series deviates" in r.body
    assert all(p["onset"] is None for p in r.data["pairs"])


def test_kpis_too_little_history_is_stated_not_invented(call: Call) -> None:
    args = {**OUTAGE, "entity_ids": ["S-TUN-001"], **span(at(1, 16), at(1, 23))}
    r = call("query_kpis", args)
    assert r.body.startswith("No baseline available")
    assert "baseline unavailable" in r.body and "have 1" in r.body
    for pair in r.data["pairs"]:
        assert pair["baseline_mean"] is None and pair["onset"] is None
        assert pair["deviation_pct"] is None and all(b is None for b in pair["baseline_series"])
        assert pair["min"] == 0.0 or pair["metric"] == "dl_volume_mb"


def test_kpis_baseline_ignores_the_future(call: Call, world: Engine) -> None:
    """Rewriting later days must not change a baseline computed at an earlier asked_at."""
    args = {
        "entity_type": "site",
        "entity_ids": ["S-TUN-003"],
        "metrics": ["dl_volume_mb"],
        **span(at(2, 12), at(2, 14)),
    }
    before = call("query_kpis", args, at(2, 14)).data["pairs"][0]["baseline_series"]
    with world.begin() as conn:
        conn.execute(text("UPDATE cell_kpis SET dl_volume_mb = 1 WHERE ts > :t"), {"t": at(2, 14)})
    try:
        after = call("query_kpis", args, at(2, 14)).data["pairs"][0]["baseline_series"]
    finally:
        load_world(make_fixture_world(), world)
        _insert_detector_rows(world)
    assert before == after and None not in before


def test_kpis_site_aggregation_sums_volumes(call: Call, world: Engine) -> None:
    with world.connect() as conn:
        expected = conn.execute(
            text(
                "SELECT SUM(dl_volume_mb) FROM cell_kpis WHERE cell_id LIKE 'C-TUN-003-%' "
                "AND ts = :t"
            ),
            {"t": at(2, 12)},
        ).scalar_one()
    args = {
        "entity_type": "site",
        "entity_ids": ["S-TUN-003"],
        "metrics": ["dl_volume_mb"],
        **span(at(2, 12), at(2, 12)),
    }
    pair = call("query_kpis", args).data["pairs"][0]
    assert pair["mean"] == pytest.approx(expected) and pair["n_steps"] == 1
    cell = call("query_kpis", {**args, "entity_type": "cell", "entity_ids": ["C-TUN-003-1"]})
    assert cell.data["pairs"][0]["mean"] < expected


def test_kpis_region_blackout_reports_no_data_steps(call: Call) -> None:
    args = {
        "entity_type": "region",
        "entity_ids": ["SFX"],
        "metrics": ["latency_ms", "availability_pct"],
        **span(at(3, 0), at(3, 4)),
    }
    r = call("query_kpis", args)
    latency = next(p for p in r.data["pairs"] if p["metric"] == "latency_ms")
    assert latency["n_no_data"] == 4 and "NO DATA" in r.body
    assert latency["mean"] is not None and latency["min"] > 0  # NULL steps are not zeros
    cells_down = call("query_kpis", {**args, "metrics": ["cells_down"]})
    assert cells_down.data["pairs"][0]["max"] == 6.0


def test_kpis_all_down_site_reports_no_data(call: Call) -> None:
    args = {
        "entity_type": "site",
        "entity_ids": ["S-TUN-001"],
        "metrics": ["latency_ms"],
        **span(at(1, 19), at(1, 21)),
    }
    r = call("query_kpis", args)
    assert "NO DATA in all 9 steps" in r.body and r.data["pairs"][0]["mean"] is None


def test_kpis_core_node_and_national(call: Call) -> None:
    dns = call(
        "query_kpis",
        {
            "entity_type": "core_node",
            "entity_ids": ["CORE-DNS-01"],
            "metrics": ["query_success_pct"],
            **span(at(1, 10), at(1, 16)),
        },
    )
    assert not dns.error and dns.data["pairs"][0]["min"] == pytest.approx(89.0)
    bad = call(
        "query_kpis",
        {
            "entity_type": "core_node",
            "entity_ids": ["CORE-DNS-01"],
            "metrics": ["throughput_gbps"],
            **span(at(1, 10), at(1, 16)),
        },
    )
    assert bad.error and "query_success_pct" in bad.error and "resolution_ms" in bad.error
    national = call(
        "query_kpis",
        {"entity_type": "national", "metrics": ["active_users"], **span(at(2, 18), at(2, 22))},
    )
    assert not national.error and national.data["pairs"][0]["entity"] == "NATIONAL"


def test_kpis_bad_entities_and_metrics(call: Call) -> None:
    link = call("query_kpis", {**OUTAGE, "entity_ids": ["LNK-TUN-01-A"]})
    assert link.error and "transport_link" in link.error and "S-TUN-001, S-TUN-002" in link.error
    unknown = call("query_kpis", {**OUTAGE, "entity_ids": ["S-SFX-01"]})
    assert unknown.error and "S-SFX-001" in unknown.error
    metric = call("query_kpis", {**OUTAGE, "metrics": ["traffic"]})
    assert metric.error and "dl_volume_mb" in metric.error
    missing = call("query_kpis", {**OUTAGE, "entity_ids": []})
    assert missing.error and "entity_ids is required" in missing.error
    partial = call("query_kpis", {**OUTAGE, "entity_ids": ["S-SFX-001", "S-NOPE-9"]})
    assert not partial.error and "Unknown site id" in partial.body
    future = call("query_kpis", OUTAGE, at(1, 0))
    assert not future.error and "nothing is visible" in future.body


def test_kpis_many_series_degrade_gracefully_within_budget(call: Call) -> None:
    args = {
        "entity_type": "site",
        "entity_ids": ["S-TUN-001", "S-TUN-002", "S-TUN-003", "S-SFX-001", "S-SFX-002"],
        "metrics": ["dl_volume_mb", "active_users", "latency_ms", "availability_pct"],
        **span(at(2, 0), at(2, 8)),
    }
    r = call("query_kpis", args)
    assert len(r.body) <= BODY_CHARS and len(r.data["pairs"]) == 20
    assert r.body.count("\n") >= 20  # every series still has at least its one-line summary


# --- anomalies --------------------------------------------------------------------------------


def test_anomalies_finished_alert_shows_severity_and_worst_entity(call: Call) -> None:
    r = call("get_anomalies", span(at(1, 12), at(1, 23)), at(2, 0))
    assert "ALR-T1 high ended" in r.body and "(3.8 h)" in r.body
    assert "availability_pct drop on 2 entities: worst S-TUN-001 z -60.0, 100 -> 0" in r.body
    assert "dl_volume_mb drop on 1 entity: worst S-TUN-001 z -20.0, 9000 -> 0" in r.body
    kinds = {ref.ref: ref.kind for ref in r.refs}
    assert kinds["ALR-T1"] == "alert" and kinds["ANM-T1"] == "anomaly"


def test_anomalies_headline_carries_alert_ids_span_and_summary(call: Call) -> None:
    r = call("get_anomalies", span(at(1, 12), at(1, 23)), at(2, 0))
    assert r.headline == r.body.splitlines()[0] and len(r.headline) <= 200
    assert r.headline.startswith("1 alert(s): ALR-T1 " + fmt(at(1, 18)) + "-" + "21:45")
    assert "Traffic and availability drop on 2 sites in TUN" in r.headline
    running = call("get_anomalies", span(at(1, 12), at(1, 23)), at(1, 20))
    assert running.headline.startswith(
        "1 alert(s), 1 ongoing: ALR-T1 " + fmt(at(1, 18)) + "-ongoing"
    )
    for hidden in ("high", "4 h", "ended", "21:45"):  # nothing from after asked_at
        assert hidden not in running.headline, hidden
    both = call("get_anomalies", span(at(0, 0), at(3, 8)), at(3, 8))
    assert both.headline.startswith("2 alert(s): ALR-T1 ") and "; ALR-T3 " in both.headline


def test_anomalies_running_alert_hides_end_size_and_severity(call: Call) -> None:
    r = call("get_anomalies", span(at(1, 12), at(1, 23)), at(1, 20))
    assert "ALR-T1 ONGOING since " + fmt(at(1, 18)) in r.body and "2.0 h so far" in r.body
    for hidden in ("high", "4 h", "4.0 h", fmt(at(1, 22)), fmt(at(1, 21.75)), "ended"):
        assert hidden not in r.body, hidden
    alert = r.data["alerts"][0]
    assert alert["ongoing"] and alert["end_at"] is None and alert["severity"] is None
    assert "Window cut at asked_at" in r.body


def test_anomalies_running_anomaly_is_measured_up_to_asked_at(call: Call) -> None:
    r = call("get_anomalies", span(at(3, 0), at(3, 8)), at(3, 1.5))
    assert "ALR-T3 ONGOING" in r.body
    assert "so far 0 vs baseline 100 (-100%)" in r.body
    assert fmt(at(3, 1.75)) not in r.body and "medium" not in r.body


def test_anomalies_alert_starting_after_asked_at_is_invisible(call: Call) -> None:
    r = call("get_anomalies", span(at(3, 0), at(3, 8)), at(3, 0.5))
    assert "No detector alerts" in r.body and not r.refs


def test_anomalies_filters(call: Call) -> None:
    window = span(at(0, 0), at(3, 8))
    assert "ALR-T3" not in call("get_anomalies", {**window, "region_id": "TUN"}).body
    assert "ALR-T1" not in call("get_anomalies", {**window, "region_id": "SFX"}).body
    by_link = call("get_anomalies", {**window, "entity_id": "LNK-TUN-01-A"})
    assert "ALR-T1" in by_link.body and "ALR-T3" not in by_link.body
    by_site = call("get_anomalies", {**window, "entity_id": "S-TUN-002"})
    assert "ALR-T1" in by_site.body and "S-TUN-002" in by_site.body
    unknown = call("get_anomalies", {**window, "entity_id": "S-TUN-09"})
    assert unknown.error and "S-TUN-001" in unknown.error
    assert call("get_anomalies", {**window, "region_id": "XX"}).error


def test_anomalies_empty_window(call: Call) -> None:
    r = call("get_anomalies", span(at(0, 0), at(0, 6)))
    assert r.body.startswith("No detector alerts") and not r.error


# --- runbooks ---------------------------------------------------------------------------------


def test_runbook_search_returns_cited_excerpts(call: Call) -> None:
    r = call("search_runbooks", {"query": "MAINS_FAILURE BATTERY_LOW site down", "k": 3})
    assert not r.error and 1 <= len(r.refs) <= 3 and len(r.body) <= BODY_CHARS
    assert all(
        ref.kind == "runbook" and ref.ref.startswith("RB-") and "#" in ref.ref for ref in r.refs
    )
    assert all(f"[{ref.ref}]" in r.body for ref in r.refs)
    assert any(ref.ref.startswith("RB-POWER-FAILURE") for ref in r.refs)


def test_runbook_search_default_and_maximum_k(call: Call) -> None:
    assert len(call("search_runbooks", {"query": "fiber cut loss of signal"}).refs) == 4
    biggest = call("search_runbooks", {"query": "fiber cut loss of signal", "k": 6})
    assert len(biggest.refs) == 6 and len(biggest.body) <= BODY_CHARS
    assert call("search_runbooks", {"query": "fiber cut", "k": 7}).error


def test_runbook_search_without_hits(call: Call) -> None:
    r = call("search_runbooks", {"query": "?!"})
    assert not r.error and r.refs  # vector search always finds the closest chunks


# --- run_sql ----------------------------------------------------------------------------------


def test_sql_returns_rows_with_a_count(call: Call) -> None:
    r = call("run_sql", {"query": "SELECT alarm_id, severity FROM alarms ORDER BY alarm_id"})
    assert not r.error and r.body.splitlines()[0].startswith("3 row(s)")
    assert "alarm_id | severity" in r.body and "ALM-000001 | critical" in r.body
    assert r.data["total_rows"] == 3 and r.data["columns"] == ["alarm_id", "severity"]


def test_sql_clamps_every_time_series_table_to_asked_at(call: Call) -> None:
    asked = at(1, 20)
    r = call("run_sql", {"query": "SELECT max(ts) AS t, count(*) AS n FROM cell_kpis"}, asked)
    assert r.data["rows"][0][0] == iso(asked)
    r = call("run_sql", {"query": "SELECT max(ts) FROM core_kpis"}, at(1, 12.9))
    assert r.data["rows"][0][0] == iso(at(1, 12.75))
    now = call("run_sql", {"query": "SELECT max(ts) FROM cell_kpis"})
    assert now.data["rows"][0][0] > iso(asked)  # the data does extend past it

    q = "SELECT count(*) AS total, count(*) FILTER (WHERE cleared_at IS NULL) AS active FROM alarms"
    assert call("run_sql", {"query": q}, asked).data["rows"][0] == [3, 3]
    assert call("run_sql", {"query": q}, at(1, 18)).data["rows"][0] == [2, 2]
    assert call("run_sql", {"query": q}).data["rows"][0] == [3, 1]

    ev = call("run_sql", {"query": "SELECT event_id, end_at FROM external_events"}, at(2, 20))
    assert ev.data["rows"] == [["EVT-001", None]]
    assert call("run_sql", {"query": "SELECT * FROM external_events"}, at(2, 18)).data["rows"] == []


def test_sql_changes_and_maintenance_are_restated_as_of_asked_at(call: Call) -> None:
    q = "SELECT change_id, status FROM changes WHERE change_id = 'CHG-2026-0002'"
    assert call("run_sql", {"query": q}, at(0, 12)).data["rows"] == [["CHG-2026-0002", "completed"]]
    assert call("run_sql", {"query": q}, at(0, 18)).data["rows"] == [
        ["CHG-2026-0002", "rolled_back"]
    ]
    n = "SELECT count(*) FROM changes"
    assert call("run_sql", {"query": n}, at(0, 12)).data["rows"] == [[1]]
    for asked, state in [(at(2, 2), "planned"), (at(2, 4), "in_progress"), (at(2, 6), "completed")]:
        r = call("run_sql", {"query": "SELECT status FROM maintenance"}, asked)
        assert r.data["rows"] == [[state]]


def test_sql_cte_and_static_tables_work(call: Call) -> None:
    q = (
        "WITH sites AS (SELECT node_id FROM nodes WHERE node_type = 'site' AND region_id = 'TUN') "
        "SELECT count(*) FROM sites"
    )
    assert call("run_sql", {"query": q}).data["rows"] == [[3]]
    assert call("run_sql", {"query": "SELECT count(*) FROM cells"}).data["rows"] == [[15]]


def test_sql_literals_are_local_time_and_percent_signs_work(call: Call) -> None:
    q = "SELECT count(*) FROM cell_kpis WHERE ts = '2026-09-02 18:00'"
    assert call("run_sql", {"query": q}).data["rows"] == [[15]]
    like = "SELECT alarm_type FROM alarms WHERE alarm_type LIKE '%LOS%'"
    assert call("run_sql", {"query": like}).data["rows"] == [["LINK_LOS"]]


def test_sql_row_cap_and_budget(call: Call) -> None:
    r = call("run_sql", {"query": "SELECT * FROM cell_kpis ORDER BY ts, cell_id"})
    assert r.data["total_rows"] > 1000 and len(r.data["rows"]) == 50
    assert r.truncated and len(r.body) <= BODY_CHARS and "row cap 50" in r.body


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM alarms",
        "UPDATE changes SET status = 'x'",
        "INSERT INTO alarms SELECT * FROM alarms",
        "DROP TABLE alarms",
        "SELECT 1; DELETE FROM alarms",
        "SELECT * INTO copy FROM alarms",
        "WITH d AS (DELETE FROM alarms RETURNING *) SELECT * FROM d",
        "SELECT * FROM gt.scenarios",
        'SELECT * FROM "gt"."scenarios"',
        "SELECT * FROM public.alarms",
        "SELECT * FROM alerts",
        "SELECT * FROM pg_catalog.pg_tables",
        "SELECT query_to_xml('select * from public.cell_kpis', true, false, '')",
    ],
)
def test_sql_rejects_writes_multiple_statements_and_hidden_data(
    call: Call, query: str, world: Engine
) -> None:
    with world.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM alarms")).scalar_one()
    r = call("run_sql", {"query": query})
    assert r.error and r.error.startswith("Query rejected") and not r.data
    with world.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM alarms")).scalar_one() == before


def test_sql_database_role_independently_blocks_gt_and_writes(agent_ro_engine: Engine) -> None:
    with pytest.raises(DBAPIError), agent_ro_engine.connect() as conn:
        conn.execute(text("SELECT * FROM gt.scenarios"))
    with pytest.raises(DBAPIError), agent_ro_engine.begin() as conn:
        conn.execute(text("DELETE FROM alarms"))


def test_sql_errors_are_readable_and_list_columns(call: Call) -> None:
    r = call("run_sql", {"query": "SELECT nope FROM alarms"})
    assert r.error and "does not exist" in r.error and "alarm_type" in r.error
    assert "WITH" not in r.error  # the wrapper is invisible to the model


def test_sql_timeout(call: Call) -> None:
    r = call("run_sql", {"query": "SELECT count(*) FROM generate_series(1, 2000000000)"})
    assert r.error and "exceeded the 5s limit" in r.error


def test_sql_empty_result(call: Call) -> None:
    r = call("run_sql", {"query": "SELECT * FROM alarms WHERE severity = 'none'"})
    assert not r.error and r.body.startswith("0 rows")


# --- cross-cutting ----------------------------------------------------------------------------

BUDGET_CALLS: list[tuple[str, dict[str, Any], datetime]] = [
    ("get_topology", {"node_id": "AGG-TUN-01"}, NOW),
    ("get_alarms", FULL, NOW),
    ("get_changes", FULL, NOW),
    ("get_maintenance", FULL, NOW),
    ("get_external_events", FULL, NOW),
    ("get_anomalies", FULL, NOW),
    ("get_anomalies", span(at(1, 12), at(1, 23)), at(1, 20)),
    ("query_kpis", OUTAGE, NOW),
    (
        "query_kpis",
        {
            **OUTAGE,
            "entity_ids": ["S-TUN-001", "S-TUN-002", "S-SFX-001"],
            "metrics": ["dl_volume_mb", "latency_ms", "active_users", "availability_pct"],
        },
        NOW,
    ),
    ("search_runbooks", {"query": "fiber cut LINK_LOS sites down", "k": 6}, NOW),
    ("run_sql", {"query": "SELECT * FROM cell_kpis"}, NOW),
    ("run_sql", {"query": "SELECT * FROM alarms"}, NOW),
]


@pytest.mark.parametrize(("name", "args", "asked"), BUDGET_CALLS)
def test_every_body_fits_the_token_budget(
    call: Call, name: str, args: dict[str, Any], asked: datetime
) -> None:
    r = call(name, args, asked)
    assert not r.error and r.headline
    assert len(r.body) / 4 <= 500, f"{name}: ~{len(r.body) // 4} tokens"
    assert r.tool == name and r.args


def test_refs_are_unique_per_call_and_typed(call: Call) -> None:
    for name, args, asked in BUDGET_CALLS:
        refs = call(name, args, asked).refs
        assert len({ref.ref for ref in refs}) == len(refs), name
        assert all(ref.summary and "\n" not in ref.summary for ref in refs), name


def test_nothing_after_asked_at_leaks_into_any_structured_payload(call: Call) -> None:
    asked = at(1, 20)
    leaks = (iso(at(1, 22)), iso(at(1, 21.75)))
    for name, args in [
        ("get_alarms", {**span(at(1, 10), at(1, 23))}),
        ("get_anomalies", {**span(at(1, 10), at(1, 23))}),
        ("get_changes", FULL),
        ("get_maintenance", FULL),
        ("get_external_events", FULL),
        ("query_kpis", {**OUTAGE, "entity_ids": ["S-TUN-001"], **span(at(1, 16), at(1, 23))}),
    ]:
        r = call(name, args, asked)
        for leak in leaks:
            assert leak not in str(r.data) and leak not in r.body, (name, leak)
