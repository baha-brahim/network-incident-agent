"""The look-alike checks of the verify step, on hand-made reports, records and topology."""

from datetime import datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from incident_agent.agent.config import AgentConfig
from incident_agent.agent.facts import Alarm, Alert, Change, Event, Facts, Window
from incident_agent.agent.lookalike import CHECKS, lookalike_problems
from incident_agent.agent.reference import Reference
from incident_agent.agent.report import Finding, Report
from incident_agent.agent.tools.timeutil import parse_time
from incident_agent.evals.runner import agent_config_for, get_variant
from tests.agent_support import make_report

DAY = "2026-09-06"
ASKED = parse_time(f"{DAY} 18:00")

# node -> (type, region, parent)
TREE: dict[str, tuple[str, str | None, str | None]] = {
    "CORE-UPF-01": ("core_upf", None, None),
    "CORE-DNS-01": ("core_dns", None, None),
    "CORE-AMF-01": ("core_amf", None, None),
    "AGG-SFX-01": ("agg_router", "SFX", "CORE-UPF-01"),
    "LNK-SFX-01-A": ("transport_link", "SFX", "AGG-SFX-01"),
    "LNK-SFX-01-B": ("transport_link", "SFX", "AGG-SFX-01"),
    "S-SFX-002": ("site", "SFX", "LNK-SFX-01-A"),
    "S-SFX-006": ("site", "SFX", "LNK-SFX-01-A"),
    "S-SFX-009": ("site", "SFX", "LNK-SFX-01-A"),
    "S-SFX-003": ("site", "SFX", "LNK-SFX-01-B"),
    "AGG-TUN-01": ("agg_router", "TUN", "CORE-UPF-01"),
    "LNK-TUN-01-A": ("transport_link", "TUN", "AGG-TUN-01"),
    "LNK-TUN-01-B": ("transport_link", "TUN", "AGG-TUN-01"),
    "LNK-TUN-02-C": ("transport_link", "TUN", "AGG-TUN-01"),
    "S-TUN-001": ("site", "TUN", "LNK-TUN-01-A"),
    "S-TUN-002": ("site", "TUN", "LNK-TUN-01-A"),
    "S-TUN-003": ("site", "TUN", "LNK-TUN-01-A"),
    "S-TUN-006": ("site", "TUN", "LNK-TUN-01-B"),
    "S-TUN-010": ("site", "TUN", "LNK-TUN-02-C"),
}
REF = Reference(
    regions={"TUN": "Grand Tunis", "SFX": "Sfax"},
    node_ids=set(TREE),
    cell_ids={"C-TUN-006-1"},
    parent_of={n: p for n, (_, _, p) in TREE.items() if p} | {"C-TUN-006-1": "S-TUN-006"},
    node_type={n: kind for n, (kind, _, _) in TREE.items()},
    region_of={n: region for n, (_, region, _) in TREE.items()},
    venue_sites={"S-TUN-001", "S-TUN-002", "S-TUN-003"},
)
SFX_SITES = ["S-SFX-002", "S-SFX-006", "S-SFX-009"]


def t(hhmm: str, day: str = DAY) -> datetime:
    return parse_time(f"{day} {hhmm}")


def at(base: str, minutes: int) -> datetime:
    return t(base) + timedelta(minutes=minutes)


def window(
    ref: str = "MW-0004",
    node: str = "LNK-SFX-01-A",
    start: str = "07:16",
    end: str = "09:55",
    impact: str = "Downstream sites offline",
) -> Window:
    return Window(ref, node, t(start), t(end), impact)


def alarm(
    ref: str = "ALM-000100",
    node: str = "LNK-SFX-01-A",
    raised: str | datetime = "07:20",
    cleared: str | datetime | None = "09:50",
    severity: str = "critical",
) -> Alarm:
    def when(v: str | datetime | None) -> datetime | None:
        return t(v) if isinstance(v, str) else v

    raised_at = when(raised)
    assert raised_at is not None
    return Alarm(ref, node, "LINK_LOS", severity, raised_at, when(cleared))


def event(
    ref: str = "EVT-003",
    region: str | None = "TUN",
    node: str | None = "S-TUN-001",
    start: str = "17:00",
    end: str | None = "20:00",
) -> Event:
    return Event(ref, region, node, t(start), t(end) if end else None)


def change(
    ref: str = "CHG-2026-0043",
    node: str = "CORE-DNS-01",
    at_: str | datetime = "13:59",
    kind: str = "config_push",
    description: str | None = None,
    rollback_of: str | None = None,
) -> Change:
    when = t(at_) if isinstance(at_, str) else at_
    return Change(ref, node, kind, when, description or f"Raise cache size on {node}", rollback_of)


def alert(
    ref: str = "ALR-0021",
    start: str = "15:00",
    end: str | None = None,
    entities: tuple[str, ...] = ("CORE-DNS-01",),
) -> Alert:
    return Alert(ref, t(start), t(end) if end else None, entities)


def facts(*items: Window | Event | Change | Alarm | Alert) -> Facts:
    out = Facts()
    for item in items:
        table: dict[str, Any] = {
            Window: out.windows,
            Event: out.events,
            Change: out.changes,
            Alarm: out.alarms,
            Alert: out.alerts,
        }[type(item)]
        table[item.ref] = item
    return out


def finding(*refs: str) -> list[Finding]:
    return [Finding(claim="A fact", basis="observed", refs=list(refs))]


def report(*cited: str, **over: Any) -> Report:
    """A report that cites exactly `cited` (make_report's own citations are replaced)."""
    return make_report(
        **{"timeline": [], "hypotheses": [], "findings": finding(*cited or ("T1",))} | over
    )


def mw_report(*cited: str, **over: Any) -> Report:
    return report(
        *(cited or ("MW-0004",)),
        **{
            "classification": "planned_maintenance",
            "root_cause_category": "planned_maintenance",
            "root_cause_node_id": "LNK-SFX-01-A",
            "affected_node_ids": SFX_SITES,
            "impact_start": f"{DAY} 07:20",
            "impact_end": None,
        }
        | over,
    )


def event_report(*cited: str, **over: Any) -> Report:
    return report(
        *(cited or ("EVT-003",)),
        **{
            "classification": "expected_event",
            "root_cause_category": "expected_event",
            "root_cause_node_id": "S-TUN-001",
            "affected_node_ids": ["S-TUN-001", "S-TUN-002"],
        }
        | over,
    )


def change_report(**over: Any) -> Report:
    return report(
        "CHG-2026-0043",
        **{
            "classification": "incident",
            "root_cause_category": "bad_change",
            "root_cause_node_id": "CORE-DNS-01",
            "affected_node_ids": [],
            "impact_start": f"{DAY} 15:00",
        }
        | over,
    )


def transport_report(**over: Any) -> Report:
    return report(
        "T1",
        **{
            "classification": "incident",
            "root_cause_category": "transport_failure",
            "root_cause_node_id": "LNK-SFX-01-A",
            "affected_node_ids": SFX_SITES,
        }
        | over,
    )


def problems(
    rep: Report, found: Facts, *, asked: datetime = ASKED, enabled: Any = CHECKS
) -> list[str]:
    return lookalike_problems(rep, found, REF, asked, enabled)


# --- maintenance_window ------------------------------------------------------------------------


def test_a_window_that_covers_the_outage_explains_it() -> None:
    assert problems(mw_report(), facts(window(), alarm())) == []


def test_an_outage_that_outlasts_the_window_by_hours_is_flagged() -> None:
    found = facts(window(), alarm(cleared="13:20"))
    assert problems(mw_report(), found) == [
        "MW-0004 on LNK-SFX-01-A ran 2026-09-06 07:16-09:55, but the outage lasted until 13:20 "
        "(ALM-000100), 205 min after the window closed. A window explains an outage only if it "
        "covers it in time and sits on the affected node or a parent; the part outside it is an "
        "unplanned incident on that node."
    ]


def test_an_outage_that_starts_before_the_window_is_flagged() -> None:
    found = facts(window(), alarm(raised="05:51"))
    text = problems(mw_report(impact_start=None), found)[0]
    assert "ALM-000100 on LNK-SFX-01-A was raised at 05:51, 85 min before the window opened" in text


def test_a_window_on_a_sibling_link_does_not_explain_it() -> None:
    found = facts(window(node="LNK-SFX-01-B"), alarm(node="LNK-SFX-01-B"))
    text = problems(mw_report(), found)[0]
    assert "MW-0004 on LNK-SFX-01-B ran" in text
    assert (
        "the affected sites S-SFX-002, S-SFX-006, S-SFX-009 are not on or below LNK-SFX-01-B"
        in text
    )


@pytest.mark.parametrize("impact", ["None expected", "none", "  NONE.", "None (monitoring only)"])
def test_a_window_that_expects_no_impact_does_not_explain_one(impact: str) -> None:
    text = problems(mw_report(), facts(window(impact=impact)))[0]
    assert f"its expected impact is {impact.strip()!r}" in text


def test_a_window_on_a_parent_explains_it() -> None:
    found = facts(window(node="AGG-SFX-01"), alarm())
    assert problems(mw_report(), found) == []
    assert problems(mw_report(), facts(window(node="CORE-UPF-01"), alarm())) == []


def test_the_window_node_is_compared_with_the_root_cause_when_no_site_is_named() -> None:
    rep = mw_report(affected_node_ids=[], root_cause_node_id="LNK-SFX-01-B")
    assert problems(rep, facts(window())) != []
    rep = mw_report(affected_node_ids=[], root_cause_node_id="LNK-SFX-01-A")
    assert problems(rep, facts(window())) == []
    nothing = mw_report(affected_node_ids=[], root_cause_node_id=None)
    assert problems(nothing, facts(window())) == []  # no place to compare: not a contradiction


def test_a_cell_counts_as_its_site() -> None:
    found = facts(window(node="LNK-TUN-01-B"))
    rep = mw_report(affected_node_ids=["C-TUN-006-1"], root_cause_node_id="S-TUN-006")
    assert problems(rep, found) == []
    assert problems(rep, facts(window(node="LNK-TUN-01-A"))) != []


@pytest.mark.parametrize(
    ("raised", "cleared", "fires"),
    [
        (at("07:16", -20), "09:50", False),
        (at("07:16", -21), "09:50", True),
        ("07:20", at("09:55", 45), False),
        ("07:20", at("09:55", 46), True),
    ],
)
def test_alarm_tolerance_edges(raised: Any, cleared: Any, fires: bool) -> None:
    found = facts(window(), alarm(raised=raised, cleared=cleared))
    assert bool(problems(mw_report(impact_start=None), found)) is fires


@pytest.mark.parametrize(
    ("start", "end", "fires"),
    [
        (at("07:16", -20), at("09:55", 45), False),
        (at("07:16", -21), None, True),
        (None, at("09:55", 46), True),
    ],
)
def test_impact_tolerance_edges(start: Any, end: Any, fires: bool) -> None:
    def local(v: datetime | None) -> str | None:
        return None if v is None else (v + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")

    rep = mw_report(impact_start=local(start), impact_end=local(end))
    assert bool(problems(rep, facts(window()))) is fires


def test_an_alarm_still_active_counts_up_to_now() -> None:
    found = facts(window(), alarm(cleared=None))
    text = problems(mw_report(), found)[0]
    assert (
        "the outage was still active at 18:00 (ALM-000100), 485 min after the window closed" in text
    )
    soon = at("09:55", 40)  # still inside the tolerance after the window closed
    assert problems(mw_report(), found, asked=soon) == []
    assert problems(mw_report(), found, asked=at("09:55", 46)) != []


def test_only_critical_and_major_alarms_on_the_window_node_or_below_count() -> None:
    long_ones = [
        alarm("ALM-1", severity="minor", cleared="13:20"),
        alarm("ALM-2", node="LNK-SFX-01-B", cleared="13:20"),  # a sibling link
        alarm("ALM-3", node="AGG-SFX-01", cleared="13:20"),  # a parent
        alarm("ALM-4", raised="11:00", cleared="13:20"),  # after the window
        alarm("ALM-5", raised="03:00", cleared="06:00"),  # before the window
    ]
    assert problems(mw_report(), facts(window(), *long_ones)) == []
    below = alarm("ALM-6", node="S-SFX-002", cleared="13:20")
    assert "ALM-6" in problems(mw_report(), facts(window(), below))[0]
    major = alarm("ALM-7", severity="major", cleared="13:20")
    assert "ALM-7" in problems(mw_report(), facts(window(), major))[0]


def test_cited_windows_are_the_candidates() -> None:
    wrong = window("MW-0005", node="LNK-SFX-01-B")
    right = window()
    both = facts(wrong, right)
    assert problems(mw_report("MW-0004"), both) == []
    assert problems(mw_report("MW-0005"), both)[0].startswith("MW-0005 on LNK-SFX-01-B")
    assert problems(mw_report("MW-0004", "MW-0005"), both) == []  # one of them explains it
    assert problems(mw_report("T1"), both) == []  # nothing cited: every window is a candidate
    assert problems(mw_report("T1"), facts(wrong)) != []
    assert problems(mw_report(" mw-0005 "), both) != []  # spelling does not matter


def test_the_best_failing_window_is_the_one_in_the_right_place() -> None:
    elsewhere = window("MW-0005", node="LNK-SFX-01-B", impact="None")  # three things wrong
    near = window(end="08:00")
    text = problems(mw_report("MW-0004", "MW-0005"), facts(elsewhere, near, alarm()))[0]
    assert text.startswith("MW-0004 on LNK-SFX-01-A")


def test_no_window_fact_or_another_verdict_never_fires() -> None:
    assert problems(mw_report(), facts(alarm(cleared="13:20"))) == []
    assert problems(mw_report(), Facts()) == []
    rep = mw_report(classification="incident", root_cause_category="transport_failure")
    assert (
        problems(
            rep,
            facts(window(node="LNK-SFX-01-B"), alarm(cleared="13:20")),
            enabled=("maintenance_window",),
        )
        == []
    )


def test_unparsable_report_times_are_not_a_contradiction() -> None:
    rep = mw_report(impact_start="early morning", impact_end="whenever")
    assert problems(rep, facts(window())) == []


# --- event_venue -------------------------------------------------------------------------------


def test_an_event_explains_its_venue_sites() -> None:
    assert problems(event_report(), facts(event())) == []
    rep = event_report(affected_node_ids=["S-TUN-001", "S-TUN-002", "S-TUN-003"])
    assert problems(rep, facts(event())) == []


def test_a_report_with_no_venue_site_among_the_affected_ones_is_flagged() -> None:
    spill_over = event_report(affected_node_ids=["S-TUN-001", "S-TUN-006"])
    assert problems(spill_over, facts(event())) == []  # a neighbour listed with the venue
    rep = event_report(affected_node_ids=["S-TUN-006"])
    assert problems(rep, facts(event())) == [
        "EVT-003 is at S-TUN-001 (venue sites: S-TUN-001, S-TUN-002, S-TUN-003). S-TUN-006 is "
        "not a venue site, so the event does not explain what happened there. An event explains "
        "only its venue sites; judge S-TUN-006 on its own evidence, and if it is where the "
        "reported symptom is worst the verdict is not expected_event."
    ]


def test_an_overlapping_alert_of_its_own_on_a_non_venue_site_is_flagged() -> None:
    found = facts(event(), alert("ALR-0019", "17:30", "19:00", ("S-TUN-006", "TUN")))
    text = problems(event_report(), found)[0]
    assert "S-TUN-006 (ALR-0019) is not a venue site" in text and "judge S-TUN-006 on" in text
    listed = event_report(affected_node_ids=["S-TUN-001", "S-TUN-006"])
    assert "S-TUN-006 (ALR-0019) is not a venue site" in problems(listed, found)[0]


def test_a_non_venue_site_in_the_same_alert_as_venue_sites_is_spill_over() -> None:
    shared = alert("ALR-0006", "17:30", "19:00", ("S-TUN-001", "S-TUN-003", "S-TUN-006"))
    assert problems(event_report(), facts(event(), shared)) == []


def test_alerts_outside_the_event_in_time_or_region_do_not_count() -> None:
    far = ("S-TUN-006",)
    for item in (
        alert("ALR-1", "12:00", "16:39", far),  # ended before the event, beyond the tolerance
        alert("ALR-2", "20:01", "22:00", far),  # began after it
        alert("ALR-3", "17:30", "19:00", ("S-SFX-002",)),  # another region
        alert("ALR-4", "17:30", "19:00", ("TUN", "CORE-DNS-01")),  # not a site
        alert("ALR-5", "17:30", "19:00", ("S-TUN-001", "S-TUN-003")),  # venue sites
    ):
        assert problems(event_report(), facts(event(), item)) == [], item.ref
    for item in (
        alert("ALR-6", "12:00", "16:40", far),  # a step can start before its cause
        alert("ALR-7", "20:00", "23:00", far),
        alert("ALR-8", "19:00", None, far),  # still ongoing
    ):
        assert problems(event_report(), facts(event(), item)) != [], item.ref


def test_an_event_in_progress_has_no_end() -> None:
    live = event(end=None)
    late = alert("ALR-9", "23:30", None, ("S-TUN-006",))
    assert "S-TUN-006 (ALR-9)" in problems(event_report(), facts(live, late))[0]


def test_a_nationwide_event_explains_every_site() -> None:
    holiday = event("EVT-010", region=None, node=None)
    rep = event_report("EVT-010", affected_node_ids=["S-SFX-002", "S-TUN-006"])
    assert problems(rep, facts(holiday, alert("ALR-1", "17:30", None, ("S-TUN-006",)))) == []


def test_an_event_without_a_venue_site_covers_its_region() -> None:
    wide = event(node=None)
    assert problems(event_report(affected_node_ids=["S-TUN-006"]), facts(wide)) == []
    text = problems(event_report(affected_node_ids=["S-SFX-002"]), facts(wide))[0]
    assert text.startswith("EVT-003 covers region TUN (venue sites: every site of TUN). ")
    assert "S-SFX-002 is not a venue site" in text


def test_several_sites_outside_the_venue_are_named_together() -> None:
    rep = event_report(affected_node_ids=["S-TUN-006", "C-TUN-006-1", "S-SFX-002"])
    text = problems(rep, facts(event()))[0]
    assert "S-TUN-006, S-SFX-002 are not venue sites" in text and "judge them on their own" in text


def test_the_event_is_chosen_like_the_window() -> None:
    far = event("EVT-004", node="S-TUN-006")
    rep = event_report(affected_node_ids=["S-TUN-006"])
    both = facts(event(), far)
    assert problems(rep, both) != []  # cites EVT-003, which is not at S-TUN-006
    assert problems(event_report("EVT-004", affected_node_ids=["S-TUN-006"]), both) == []
    assert problems(event_report("T1", affected_node_ids=["S-TUN-006"]), both) == []


def test_no_event_fact_or_another_verdict_never_fires() -> None:
    far = event_report(affected_node_ids=["S-TUN-006"])
    assert problems(far, Facts()) == []
    assert problems(far.model_copy(update={"classification": "incident"}), facts(event())) == []


# --- change_timing -----------------------------------------------------------------------------


def dns_facts(*more: Any, onset: str = "15:00") -> Facts:
    return facts(change(), alert(start=onset), *more)


def test_a_change_an_hour_before_the_onset_is_flagged_with_its_batch() -> None:
    batch = [
        change("CHG-2026-0044", "CORE-UPF-01", "14:03"),
        change("CHG-2026-0045", "CORE-AMF-01", "13:55"),
        change("CHG-2026-0046", "CORE-DNS-01", "14:30", kind="rollback", rollback_of="CHG-1"),
        change("CHG-2026-0047", "S-SFX-002", "14:00", kind="software_upgrade"),  # other type
        change("CHG-2026-0048", "S-SFX-003", "14:30"),  # too far apart
        change("CHG-2026-0049", "S-SFX-006", "14:00", description="Another thing"),
    ]
    assert problems(change_report(), dns_facts(*batch)) == [
        "CHG-2026-0043 was applied to CORE-DNS-01 at 13:59, but the degradation began at 15:00 "
        "(ALR-0021), 61 min later. A change takes effect when it lands, so this timing does not "
        "support bad_change. The same change was applied to CORE-AMF-01 and CORE-UPF-01 at that "
        "time; if they stayed healthy, that is more evidence against it. Consider a fault of "
        "the node itself."
    ]


def test_a_change_without_a_batch_ends_with_the_node_itself() -> None:
    text = problems(change_report(), dns_facts())[0]
    assert text.endswith("bad_change. Consider a fault of the node itself.")


def test_a_change_just_after_the_onset_step_starts_is_fine() -> None:
    found = facts(change(at_="14:12"), alert(start="14:00"))
    assert problems(change_report(impact_start=f"{DAY} 14:00"), found) == []


@pytest.mark.parametrize(("minutes", "fires"), [(-20, False), (-21, True), (30, False), (31, True)])
def test_the_impact_start_must_lie_around_the_change(minutes: int, fires: bool) -> None:
    found = facts(change(at_="14:00"))
    start = (t("14:00") + timedelta(minutes=minutes, hours=1)).strftime("%Y-%m-%d %H:%M")
    assert bool(problems(change_report(impact_start=start), found)) is fires


def test_an_alert_on_the_changed_node_must_start_around_the_change() -> None:
    assert problems(change_report(impact_start=None), dns_facts()) != []
    text = problems(change_report(impact_start=None), dns_facts())[0]
    assert "began at 15:00 (ALR-0021), 61 min later" in text
    assert problems(change_report(impact_start=None), facts(change())) == []  # no alert at all
    # An alert that started 30 minutes after the change is close enough; 31 is not.
    assert problems(change_report(impact_start=None), dns_facts(onset="14:29")) == []
    assert problems(change_report(impact_start=None), dns_facts(onset="14:30")) != []
    # One alert near the change is enough, whatever else the detector found.
    assert problems(change_report(impact_start=None), dns_facts(alert("ALR-2", "14:10"))) == []


def test_alerts_are_relevant_through_the_node_its_descendants_or_the_affected_nodes() -> None:
    other = alert("ALR-7", "15:30", entities=("S-SFX-002", "SFX"))
    rep = change_report(impact_start=None)
    assert problems(rep, facts(change(), other)) == []  # unrelated alert
    below = alert("ALR-8", "15:30", entities=("S-SFX-002",))
    on_child = change_report(root_cause_node_id="LNK-SFX-01-A", impact_start=None)
    assert "ALR-8" in problems(on_child, facts(change(node="LNK-SFX-01-A"), below))[0]
    listed = change_report(affected_node_ids=["S-SFX-002"], impact_start=None)
    assert "ALR-8" in problems(listed, facts(change(), below))[0]


def test_a_rollback_is_not_the_change() -> None:
    rolled = change("CHG-2026-0050", "CORE-DNS-01", "14:55", kind="rollback", rollback_of="X")
    assert problems(change_report(), facts(rolled, change(), alert())) != []
    only_rollback = problems(change_report(), facts(rolled, alert()))
    assert only_rollback == [
        "bad_change is named on CORE-DNS-01, but no change on CORE-DNS-01 is in the tool "
        "results; name the node the change was applied to."
    ]


def test_a_change_on_another_node_is_not_the_named_one() -> None:
    elsewhere = change("CHG-2026-0099", "CORE-AMF-01", "14:55")
    assert problems(change_report(), facts(elsewhere)) == [
        "bad_change is named on CORE-DNS-01, but no change on CORE-DNS-01 is in the tool "
        "results; name the node the change was applied to."
    ]


def test_the_closest_change_is_reported() -> None:
    far = change("CHG-2026-0001", at_="09:00")
    near = change("CHG-2026-0002", at_="14:25")
    text = problems(change_report(), facts(far, near, alert()))[0]
    assert text.startswith("CHG-2026-0002 was applied to CORE-DNS-01 at 14:25")
    assert (
        problems(change_report(), facts(far, change("CHG-2026-0003", at_="14:50"), alert())) == []
    )


def test_a_degradation_before_the_change_says_so() -> None:
    found = facts(change(at_="16:00"), alert(start="15:00"))
    text = problems(change_report(), found)[0]
    assert (
        "at 16:00, but the degradation began at 15:00 (ALR-0021), 60 min before the change" in text
    )


def test_the_date_is_shown_when_the_days_differ() -> None:
    found = facts(change(at_=parse_time("2026-09-05 23:50")), alert(start="00:30"))
    text = problems(change_report(impact_start=None), found)[0]
    assert "at 23:50, but the degradation began at 2026-09-06 00:30" not in text
    assert "at 2026-09-05 23:50, but the degradation began at 2026-09-06 00:30" in text


def test_no_change_fact_or_another_category_never_fires() -> None:
    assert problems(change_report(), facts(alert())) == []
    assert problems(change_report(), Facts()) == []
    capacity = change_report(root_cause_category="capacity")
    assert problems(capacity, dns_facts()) == []
    assert problems(change_report(root_cause_node_id=None), dns_facts()) == []


# --- shared_parent -----------------------------------------------------------------------------


def test_naming_the_router_above_the_shared_link_without_an_alarm_is_flagged() -> None:
    rep = transport_report(root_cause_node_id="AGG-SFX-01")
    assert problems(rep, Facts()) == [
        "The affected sites S-SFX-002, S-SFX-006, S-SFX-009 share LNK-SFX-01-A as their lowest "
        "common parent and no alarm sits on AGG-SFX-01. A failure of AGG-SFX-01 would also have "
        "hit its other children; without a signal of its own there, name LNK-SFX-01-A as the "
        "root cause node."
    ]
    on_link = facts(alarm(node="LNK-SFX-01-A"))
    assert problems(rep, on_link) != []  # an alarm on the link is not an alarm on the router


def test_the_shared_link_or_a_router_with_its_own_alarm_passes() -> None:
    assert problems(transport_report(), Facts()) == []
    router = transport_report(root_cause_node_id="AGG-SFX-01")
    assert problems(router, facts(alarm(node="AGG-SFX-01", severity="minor"))) == []
    degraded = router.model_copy(update={"root_cause_category": "transport_degradation"})
    assert problems(degraded, Facts()) != []
    assert problems(degraded, facts(alarm(node="AGG-SFX-01"))) == []


def test_sites_under_two_links_with_an_alarm_on_the_named_link_pass() -> None:
    rep = transport_report(affected_node_ids=["S-SFX-002", "S-SFX-003"])
    assert problems(rep, facts(alarm(node="LNK-SFX-01-A"))) == []
    assert problems(rep, Facts()) == []  # two things may have happened: no advice either way
    assert (
        problems(
            transport_report(
                affected_node_ids=["S-SFX-002", "S-SFX-003"], root_cause_node_id="AGG-SFX-01"
            ),
            Facts(),
        )
        == []
    )


def test_naming_one_of_several_sites_is_flagged_even_with_an_alarm() -> None:
    rep = transport_report(root_cause_node_id="S-SFX-002")
    text = problems(rep, facts(alarm(node="S-SFX-002")))[0]
    assert "S-SFX-002 is one of them, not their parent" in text
    assert "name LNK-SFX-01-A (or a node above it that carries an alarm)" in text


def test_shared_parent_needs_two_sites_a_root_and_a_transport_category() -> None:
    one = transport_report(affected_node_ids=["S-SFX-002"], root_cause_node_id="AGG-SFX-01")
    assert problems(one, Facts()) == []
    none = transport_report(root_cause_node_id=None)
    assert problems(none, Facts()) == []
    capacity = transport_report(root_cause_node_id="AGG-SFX-01", root_cause_category="capacity")
    assert problems(capacity, Facts()) == []
    cells = transport_report(root_cause_node_id="AGG-TUN-01", affected_node_ids=["C-TUN-006-1"])
    assert problems(cells, Facts()) == []
    across = transport_report(affected_node_ids=["S-SFX-002", "S-TUN-001"])
    assert problems(across, Facts(), enabled=("shared_parent",)) == []  # the link is beside it
    lone = transport_report(
        affected_node_ids=["S-SFX-002", "S-SFX-003"], root_cause_node_id="S-SFX-002"
    )
    assert problems(lone, Facts()) == []  # the other site hangs under another link


# --- planned_outage ----------------------------------------------------------------------------


def outage_report(**over: Any) -> Report:
    return report(
        "T1",
        **{
            "classification": "incident",
            "root_cause_category": "transport_failure",
            "root_cause_node_id": "LNK-TUN-02-C",
            "affected_node_ids": ["S-TUN-010"],
        }
        | over,
    )


def planned(**over: Any) -> Window:
    base: dict[str, Any] = {
        "ref": "MW-0012",
        "node": "LNK-TUN-02-C",
        "start": "11:37",
        "end": "14:09",
        "impact": "Downstream sites offline during splicing",
    }
    return window(**base | over)


def outage(**over: Any) -> Alarm:
    base: dict[str, Any] = {
        "ref": "ALM-000508",
        "node": "LNK-TUN-02-C",
        "raised": "11:43",
        "cleared": "13:54",
    }
    return alarm(**base | over)


def test_an_incident_whose_outage_lies_inside_a_window_on_its_node_is_flagged() -> None:
    assert problems(outage_report(), facts(planned(), outage())) == [
        "The outage under LNK-TUN-02-C (ALM-000508, 11:43-13:54) lies inside maintenance window "
        "MW-0012 on LNK-TUN-02-C (11:37-14:09, expected impact: Downstream sites offline during "
        "splicing). That is planned work, not an incident. If other nodes failed outside any "
        "window, the incident is there: name that node and its cause; otherwise the verdict is "
        "planned_maintenance."
    ]


def test_an_alarm_that_clears_hours_after_the_window_is_a_real_incident() -> None:
    assert problems(outage_report(), facts(planned(), outage(cleared="17:09"))) == []
    assert problems(outage_report(), facts(planned(), outage(raised="10:00"))) == []
    one_bad = [outage(), outage(ref="ALM-2", cleared="17:09")]
    assert problems(outage_report(), facts(planned(), *one_bad)) == []  # every alarm must be inside


def test_planned_outage_tolerance_edges() -> None:
    assert problems(outage_report(), facts(planned(), outage(raised=at("11:37", -20)))) != []
    assert problems(outage_report(), facts(planned(), outage(raised=at("11:37", -21)))) == []
    assert problems(outage_report(), facts(planned(), outage(cleared=at("14:09", 45)))) != []
    assert problems(outage_report(), facts(planned(), outage(cleared=at("14:09", 46)))) == []


def test_planned_outage_looks_at_parents_children_and_impact() -> None:
    parent = planned(node="AGG-TUN-01")
    assert (
        "maintenance window MW-0012 on AGG-TUN-01"
        in problems(outage_report(), facts(parent, outage()))[0]
    )
    below = outage(node="S-TUN-010")
    assert "(ALM-000508, 11:43-13:54)" in problems(outage_report(), facts(planned(), below))[0]
    assert problems(outage_report(), facts(planned(node="LNK-TUN-01-A"), outage())) == []  # sibling
    assert problems(outage_report(), facts(planned(), outage(node="LNK-TUN-01-A"))) == []
    assert problems(outage_report(), facts(planned(impact="None expected"), outage())) == []
    assert problems(outage_report(), facts(planned(), outage(severity="minor"))) == []
    child_window = planned(node="S-TUN-010")  # a window below the named node does not cover it
    assert problems(outage_report(), facts(child_window, outage())) == []


def test_several_alarms_are_listed_and_an_active_one_runs_to_now() -> None:
    both = facts(planned(), outage(), outage(ref="ALM-000509", node="S-TUN-010", raised="11:50"))
    text = problems(outage_report(), both)[0]
    assert "(ALM-000508, ALM-000509, 11:43-13:54)" in text
    active = facts(planned(), outage(cleared=None))
    assert "(ALM-000508, 11:43-now)" in problems(outage_report(), active, asked=t("14:30"))[0]
    assert problems(outage_report(), active) == []  # still active hours after the window


def test_planned_outage_needs_an_incident_a_root_and_an_alarm() -> None:
    assert problems(outage_report(), facts(planned())) == []
    assert problems(outage_report(root_cause_node_id=None), facts(planned(), outage())) == []
    inconclusive = outage_report(classification="inconclusive", root_cause_category="unknown")
    assert problems(inconclusive, facts(planned(), outage())) == []


# --- all of them -------------------------------------------------------------------------------


def test_no_enabled_check_returns_nothing_and_a_subset_runs_alone() -> None:
    found = facts(planned(), outage())
    assert problems(outage_report(), found, enabled=()) == []
    assert problems(outage_report(), found, enabled=("event_venue",)) == []
    assert problems(outage_report(), found, enabled=("planned_outage",)) != []
    assert problems(outage_report(), found, enabled=["planned_outage"]) != []


def test_the_config_rejects_unknown_checks_and_defaults_to_all() -> None:
    assert AgentConfig().lookalike_checks == CHECKS and AgentConfig().max_lookalike_repairs == 1
    assert AgentConfig(lookalike_checks=()).lookalike_checks == ()
    assert AgentConfig(lookalike_checks=("shared_parent",)).lookalike_checks == ("shared_parent",)
    with pytest.raises(ValidationError, match="unknown look-alike check"):
        AgentConfig(lookalike_checks=("shared_parent", "nope"))
    with pytest.raises(ValidationError):
        AgentConfig(max_lookalike_repairs=-1)


def test_the_no_checks_variant_turns_the_stage_off() -> None:
    assert agent_config_for(get_variant("no-checks")).lookalike_checks == ()
    assert agent_config_for(get_variant("default")).lookalike_checks == CHECKS
