"""The rows the tools return, as the verify step keeps and parses them. No database."""

from datetime import UTC, datetime
from typing import Any

import pytest

from incident_agent.agent.facts import Alarm, Alert, Change, Event, Facts, Window, rows_of
from incident_agent.agent.reference import Reference, _attrs

# Rows shaped like the `data` payloads of the tools (see agent/tools/*.py).
WINDOW_ROW = {
    "mw_id": "MW-0004",
    "node_id": "LNK-SAH-01-B",
    "start_at": "2026-09-06T06:16:00+00:00",
    "end_at": "2026-09-06T08:55:00+00:00",
    "description": "Fiber splicing",
    "expected_impact": "Downstream sites offline",
    "state": "completed",
    "relation": "",
}
EVENT_ROW = {
    "event_id": "EVT-003",
    "event_type": "stadium_event",
    "region_id": "TUN",
    "node_id": "S-TUN-001",
    "start_at": "2026-09-06T17:00:00+00:00",
    "end_at": "2026-09-06T20:00:00+00:00",
    "in_progress": False,
    "description": "Football match",
}
LIVE_EVENT_ROW = EVENT_ROW | {"event_id": "EVT-004", "end_at": None, "in_progress": True}
HOLIDAY_ROW = EVENT_ROW | {"event_id": "EVT-005", "region_id": None, "node_id": None}
CHANGE_ROW = {
    "change_id": "CHG-2026-0043",
    "node_id": "CORE-DNS-01",
    "change_type": "config_push",
    "executed_at": "2026-09-02T12:59:00+00:00",
    "description": "Raise cache size on CORE-DNS-01",
    "rollback_of": None,
    "rolled_back": False,
    "relation": "",
}
ROLLBACK_ROW = CHANGE_ROW | {
    "change_id": "CHG-2026-0044",
    "change_type": "rollback",
    "rollback_of": "CHG-2026-0043",
}
ALARM_ROW = {
    "alarm_id": "ALM-000100",
    "node_id": "LNK-SAH-01-B",
    "alarm_type": "LINK_LOS",
    "severity": "critical",
    "raised_at": "2026-09-06T06:20:00+00:00",
    "cleared_at": "2026-09-06T12:20:00+00:00",
    "active": False,
}
ACTIVE_ALARM_ROW = ALARM_ROW | {"alarm_id": "ALM-000101", "cleared_at": None, "active": True}
GROUPED_ALARM_ROW = {  # minor and warning alarms are folded into one row per node and type
    "group": True,
    "count": 4,
    "alarm_id": "ALM-000200",
    "alarm_ids": ["ALM-000200", "ALM-000201", "ALM-000202", "ALM-000203"],
    "node_id": "S-SAH-004",
    "alarm_type": "HIGH_PRB",
    "severity": "warning",
    "raised_at": "2026-09-06T05:00:00+00:00",
    "last_raised_at": "2026-09-06T07:00:00+00:00",
    "n_active": 1,
    "active": True,
}
ALERT_ROW = {
    "alert_id": "ALR-0021",
    "start_at": "2026-09-02T14:00:00+00:00",
    "end_at": None,
    "ongoing": True,
    "span": "2026-09-02 15:00-ongoing",
    "short": "x",
    "severity": None,
    "score": 99.0,
    "n_visible_anomalies": 3,
    "entities": ["S-TUN-001", "TUN"],
    "metrics": ["availability_pct"],
}


def payload(key: str, *rows: dict[str, Any]) -> dict[str, Any]:
    return {"window": ["a", "b"], "n_total": len(rows), key: list(rows)}


def test_rows_of_keys_each_tool_s_rows_by_evidence_ref() -> None:
    assert rows_of("get_maintenance", payload("rows", WINDOW_ROW)) == {"MW-0004": WINDOW_ROW}
    both = rows_of("get_external_events", payload("rows", EVENT_ROW, LIVE_EVENT_ROW))
    assert list(both) == ["EVT-003", "EVT-004"]
    assert list(rows_of("get_changes", payload("rows", CHANGE_ROW, ROLLBACK_ROW))) == [
        "CHG-2026-0043",
        "CHG-2026-0044",
    ]
    alarms = rows_of("get_alarms", payload("rows", ALARM_ROW, GROUPED_ALARM_ROW))
    assert list(alarms) == ["ALM-000100", "ALM-000200"]
    assert rows_of("get_anomalies", payload("alerts", ALERT_ROW)) == {"ALR-0021": ALERT_ROW}


@pytest.mark.parametrize("tool", ["query_kpis", "get_topology", "search_runbooks", "nope", ""])
def test_rows_of_ignores_tools_the_checks_do_not_read(tool: str) -> None:
    assert rows_of(tool, payload("rows", WINDOW_ROW)) == {}


@pytest.mark.parametrize(
    "data",
    [
        None,
        "text",
        [],
        {},
        {"rows": None},
        {"rows": "x"},
        {"rows": [None, 3, "x", {}, {"mw_id": None}, {"mw_id": ""}, {"mw_id": 7}]},
        {"n_total": 0, "rows": []},
    ],
)
def test_rows_of_never_raises_on_malformed_data(data: Any) -> None:
    assert rows_of("get_maintenance", data) == {}


def test_rows_of_uses_the_alert_list_only_for_anomalies() -> None:
    assert rows_of("get_anomalies", payload("rows", ALERT_ROW)) == {}
    assert rows_of("get_maintenance", payload("alerts", WINDOW_ROW)) == {}


def test_facts_parse_every_kind_with_tz_aware_times() -> None:
    rows: dict[str, dict[str, Any]] = {}
    rows |= rows_of("get_maintenance", payload("rows", WINDOW_ROW))
    rows |= rows_of("get_external_events", payload("rows", EVENT_ROW, LIVE_EVENT_ROW, HOLIDAY_ROW))
    rows |= rows_of("get_changes", payload("rows", CHANGE_ROW, ROLLBACK_ROW))
    rows |= rows_of("get_alarms", payload("rows", ALARM_ROW, ACTIVE_ALARM_ROW, GROUPED_ALARM_ROW))
    rows |= rows_of("get_anomalies", payload("alerts", ALERT_ROW))
    facts = Facts.from_rows(rows)

    assert facts.windows == {
        "MW-0004": Window(
            "MW-0004",
            "LNK-SAH-01-B",
            datetime(2026, 9, 6, 6, 16, tzinfo=UTC),
            datetime(2026, 9, 6, 8, 55, tzinfo=UTC),
            "Downstream sites offline",
        )
    }
    assert facts.events["EVT-003"] == Event(
        "EVT-003",
        "TUN",
        "S-TUN-001",
        datetime(2026, 9, 6, 17, 0, tzinfo=UTC),
        datetime(2026, 9, 6, 20, 0, tzinfo=UTC),
    )
    assert facts.events["EVT-004"].end is None  # in progress
    assert facts.events["EVT-005"].region_id is None and facts.events["EVT-005"].node_id is None
    assert facts.changes["CHG-2026-0043"] == Change(
        "CHG-2026-0043",
        "CORE-DNS-01",
        "config_push",
        datetime(2026, 9, 2, 12, 59, tzinfo=UTC),
        "Raise cache size on CORE-DNS-01",
        None,
    )
    assert facts.changes["CHG-2026-0044"].rollback_of == "CHG-2026-0043"
    assert facts.alarms["ALM-000100"] == Alarm(
        "ALM-000100",
        "LNK-SAH-01-B",
        "LINK_LOS",
        "critical",
        datetime(2026, 9, 6, 6, 20, tzinfo=UTC),
        datetime(2026, 9, 6, 12, 20, tzinfo=UTC),
    )
    assert facts.alarms["ALM-000101"].cleared is None  # active
    grouped = facts.alarms["ALM-000200"]  # the group stands for its first alarm
    assert (grouped.node_id, grouped.severity, grouped.cleared) == ("S-SAH-004", "warning", None)
    assert facts.alerts["ALR-0021"] == Alert(
        "ALR-0021", datetime(2026, 9, 2, 14, 0, tzinfo=UTC), None, ("S-TUN-001", "TUN")
    )
    for kind in (facts.windows, facts.events, facts.changes, facts.alarms, facts.alerts):
        for item in kind.values():
            assert all(v.tzinfo is not None for v in vars(item).values() if isinstance(v, datetime))


def test_ids_are_compared_upper_case_and_trimmed() -> None:
    row = WINDOW_ROW | {"mw_id": " mw-0004 ", "node_id": "lnk-sah-01-b"}
    facts = Facts.from_rows(rows_of("get_maintenance", payload("rows", row)))
    assert list(facts.windows) == ["MW-0004"]
    assert facts.windows["MW-0004"].node_id == "LNK-SAH-01-B"


def test_a_row_that_cannot_be_parsed_is_skipped() -> None:
    bad_time = WINDOW_ROW | {"mw_id": "MW-0005", "start_at": "yesterday"}
    no_end = WINDOW_ROW | {"mw_id": "MW-0006", "end_at": None}
    missing = {k: v for k, v in WINDOW_ROW.items() if k != "node_id"} | {"mw_id": "MW-0007"}
    rows = rows_of("get_maintenance", payload("rows", WINDOW_ROW, bad_time, no_end, missing))
    assert list(Facts.from_rows(rows).windows) == ["MW-0004"]
    odd = {"X": {"unknown": 1}, "Y": "not a row", "Z": {"alert_id": "ALR-1", "start_at": 5}}
    assert Facts.from_rows(odd) == Facts()  # type: ignore[arg-type]
    assert Facts.from_rows({}) == Facts()


def test_alert_entities_must_be_a_list() -> None:
    row = ALERT_ROW | {"entities": "S-TUN-001"}
    assert Facts.from_rows({"ALR-0021": row}).alerts["ALR-0021"].entities == ()


def test_node_attrs_arrive_as_a_dict_or_a_json_string() -> None:
    assert _attrs({"near_venue": True}) == {"near_venue": True}
    assert _attrs('{"near_venue": true}') == {"near_venue": True}
    assert _attrs("not json") == {} and _attrs(None) == {} and _attrs("[1]") == {}


def test_reference_walks_the_tree() -> None:
    ref = Reference(
        parent_of={
            "S-A-1": "LNK-A",
            "S-A-2": "LNK-A",
            "S-B-1": "LNK-B",
            "C-A-1-1": "S-A-1",
            "LNK-A": "AGG",
            "LNK-B": "AGG",
            "AGG": "CORE",
        }
    )
    assert ref.descendants("LNK-A") == ["S-A-1", "S-A-2", "C-A-1-1"]
    assert ref.descendants("AGG")[:2] == ["LNK-A", "LNK-B"] and len(ref.descendants("AGG")) == 6
    assert ref.descendants("S-B-1") == [] and ref.descendants("unknown") == []
    assert ref.lowest_common_ancestor(["S-A-1", "S-A-2"]) == "LNK-A"
    assert ref.lowest_common_ancestor(["S-A-1", "S-B-1"]) == "AGG"
    assert ref.lowest_common_ancestor(["C-A-1-1", "S-A-2", "S-B-1"]) == "AGG"
    assert ref.lowest_common_ancestor(["S-A-1"]) is None
    assert ref.lowest_common_ancestor(["S-A-1", "S-A-1"]) is None  # one node twice
    assert ref.lowest_common_ancestor([]) is None
    assert ref.lowest_common_ancestor(["CORE", "S-A-1"]) is None  # nothing above CORE
    assert Reference().lowest_common_ancestor(["S-A-1", "S-A-2"]) is None
