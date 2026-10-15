"""Look-alike checks: does a report contradict records the run itself fetched?

A maintenance window, a stadium event and a recent change each look like a cause. A check fires
only when fetched records positively contradict the verdict; a record that was never fetched never
fires one. Each problem is a sentence that states the facts and the rule they break, because it is
what the model is given to correct the report.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from incident_agent.agent.facts import Alarm, Change, Event, Facts, Window
from incident_agent.agent.reference import Reference
from incident_agent.agent.report import Report, all_refs
from incident_agent.agent.tools.common import join_ids
from incident_agent.agent.tools.timeutil import (
    TimeParseError,
    as_utc,
    fmt,
    fmt_hm,
    parse_time,
    to_local,
)

CHECKS = ("maintenance_window", "event_venue", "change_timing", "shared_parent", "planned_outage")

BEFORE = timedelta(
    minutes=20
)  # a KPI step, so an alert or impact start, can begin before its cause
AFTER = timedelta(minutes=45)  # recovery is seen late
CHANGE_AFTER = timedelta(minutes=30)
BATCH = timedelta(minutes=10)  # changes this close together count as one rollout
MAX_PROBLEMS = 4
OUTAGE = ("critical", "major")
TRANSPORT = ("transport_failure", "transport_degradation")
_NODE_ID = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")


@dataclass(frozen=True)
class _Case:
    """The report, the records and the network, with the shared definitions worked out once."""

    report: Report
    facts: Facts
    reference: Reference
    asked_at: datetime
    root: str | None  # root cause node, upper-case
    sites: tuple[str, ...]  # affected sites; a cell counts as its site


def _up(value: str | None) -> str:
    return (value or "").strip().upper()


def _affected_sites(report: Report, root: str | None, reference: Reference) -> tuple[str, ...]:
    sites: list[str] = []
    for raw in report.affected_node_ids:
        node = _up(raw)
        site = reference.parent_of.get(node) if node in reference.cell_ids else node
        if site and reference.node_type.get(site) == "site" and site not in sites:
            sites.append(site)
    if not sites and root and reference.node_type.get(root) == "site":
        sites.append(root)
    return tuple(sites)


def _time(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        return parse_time(value)
    except TimeParseError:
        return None


def _minutes(delta: timedelta) -> int:
    return round(delta.total_seconds() / 60)


def _hm(dt: datetime, like: datetime) -> str:
    """HH:MM, with the date when it is not the local day of `like`."""
    return fmt_hm(dt) if to_local(dt).date() == to_local(like).date() else fmt(dt)


def _span(start: datetime, end: datetime | None) -> str:
    """'11:43-13:54'; the date is added to both ends when they fall on different days."""
    if end is None:
        return f"{_hm(start, start)}-now"
    if to_local(start).date() == to_local(end).date():
        return f"{fmt_hm(start)}-{fmt_hm(end)}"
    return f"{fmt(start)}-{fmt(end)}"


def _covers(reference: Reference, holder: str, node: str) -> bool:
    """True if `holder` is `node` or one of its ancestors."""
    return holder == node or holder in reference.ancestors(node)


def _has_impact(window: Window) -> bool:
    return not window.expected_impact.strip().lower().startswith("none")


def _outage_alarms(case: _Case, nodes: set[str], window: Window) -> list[Alarm]:
    """Critical or major alarms on `nodes` whose interval overlaps the window."""
    return [
        a
        for a in case.facts.alarms.values()
        if a.severity in OUTAGE
        and a.node_id in nodes
        and a.raised <= window.end
        and (a.cleared is None or a.cleared >= window.start)
    ]


def _alarm_gaps(case: _Case, alarm: Alarm, window: Window) -> tuple[timedelta, timedelta]:
    """How long before the window the alarm was raised, and how long after it the alarm lasted.

    A value is positive only when it exceeds the tolerance; an alarm still active counts up to
    `asked_at`.
    """
    early = window.start - alarm.raised
    late = (alarm.cleared or case.asked_at) - window.end
    return (early if early > BEFORE else timedelta(0), late if late > AFTER else timedelta(0))


def _cited(report: Report) -> set[str]:
    return {_up(r) for r in all_refs(report)}


# --- maintenance_window ------------------------------------------------------------------------


@dataclass(frozen=True)
class _WindowVerdict:
    window: Window
    place_ok: bool
    reasons: list[str]


def _judge_window(case: _Case, window: Window) -> _WindowVerdict:
    report, ref = case.report, case.reference
    reasons: list[str] = []
    if not _has_impact(window):
        reasons.append(f"its expected impact is {window.expected_impact.strip()!r}")
    targets = case.sites or ((case.root,) if case.root else ())
    outside = [t for t in targets if not _covers(ref, window.node_id, t)]
    if outside:
        label = "the affected site" if case.sites else "the root cause node"
        plural = "s" if len(outside) > 1 and case.sites else ""
        verb = "are" if len(outside) > 1 else "is"
        reasons.append(
            f"{label}{plural} {', '.join(outside)} {verb} not on or below {window.node_id}"
        )
    start, end = _time(report.impact_start), _time(report.impact_end)
    if start is not None and start < window.start - BEFORE:
        reasons.append(
            f"the impact began at {_hm(start, window.start)}, "
            f"{_minutes(window.start - start)} min before the window opened"
        )
    nodes = {window.node_id, *ref.descendants(window.node_id)}
    gaps = [(a, *_alarm_gaps(case, a, window)) for a in _outage_alarms(case, nodes, window)]
    early = max((g for g in gaps if g[1]), key=lambda g: g[1], default=None)
    if early:
        alarm, gap, _ = early
        reasons.append(
            f"{alarm.ref} on {alarm.node_id} was raised at {_hm(alarm.raised, window.start)}, "
            f"{_minutes(gap)} min before the window opened"
        )
    late = max((g for g in gaps if g[2]), key=lambda g: g[2], default=None)
    if late:
        alarm, _, gap = late
        until = (
            f"lasted until {_hm(alarm.cleared, window.end)}"
            if alarm.cleared
            else f"was still active at {_hm(case.asked_at, window.end)}"
        )
        reasons.append(
            f"the outage {until} ({alarm.ref}), {_minutes(gap)} min after the window closed"
        )
    elif end is not None and end > window.end + AFTER:
        reasons.append(
            f"the impact lasted until {_hm(end, window.end)}, "
            f"{_minutes(end - window.end)} min after the window closed"
        )
    return _WindowVerdict(window, not outside, reasons)


def _maintenance_window(case: _Case) -> list[str]:
    if case.report.classification != "planned_maintenance":
        return []
    everything = list(case.facts.windows.values())
    cited = _cited(case.report)
    candidates = [w for w in everything if w.ref in cited] or everything
    if not candidates:
        return []
    verdicts = [_judge_window(case, w) for w in candidates]
    if any(not v.reasons for v in verdicts):
        return []
    best = min(verdicts, key=lambda v: (not v.place_ok, len(v.reasons)))
    w = best.window
    return [
        f"{w.ref} on {w.node_id} ran {fmt(w.start)}-{_hm(w.end, w.start)}, "
        f"but {'; '.join(best.reasons)}. A window explains an outage only if it covers it in "
        "time and sits on the affected node or a parent; the part outside it is an unplanned "
        "incident on that node."
    ]


# --- event_venue -------------------------------------------------------------------------------


def _sites_of_region(reference: Reference, region: str) -> set[str]:
    return {
        n
        for n, kind in reference.node_type.items()
        if kind == "site" and reference.region_of.get(n) == region
    }


def _venue_sites(reference: Reference, event: Event, region: str) -> set[str]:
    if event.node_id is None:
        return _sites_of_region(reference, region)
    nearby = {s for s in reference.venue_sites if reference.region_of.get(s) == region}
    return {event.node_id, *nearby}


def _unexplained_sites(
    case: _Case, event: Event, region: str, venue: set[str]
) -> dict[str, str | None]:
    """Sites the event cannot explain -> the alert that shows them (None: the report's own list).

    A site next to the venue that shares an alert with venue sites is spill-over and is left
    alone. What an event cannot explain is an alert of its own on sites away from the venue, or
    a report in which no affected site is a venue site.
    """
    sites: dict[str, str | None] = {}
    if case.sites and not any(s in venue for s in case.sites):
        sites.update(dict.fromkeys(case.sites))
    for alert in sorted(case.facts.alerts.values(), key=lambda a: (a.start, a.ref)):
        starts_in_time = event.end is None or alert.start <= event.end
        ends_in_time = alert.end is None or alert.end >= event.start - BEFORE
        if not (starts_in_time and ends_in_time):
            continue
        seen = [
            e
            for e in alert.entities
            if case.reference.node_type.get(e) == "site"
            and case.reference.region_of.get(e) == region
        ]
        if seen and not any(s in venue for s in seen):
            for site in seen:
                if sites.get(site) is None:
                    sites[site] = alert.ref
    return sites


def _event_venue(case: _Case) -> list[str]:
    if case.report.classification != "expected_event":
        return []
    everything = list(case.facts.events.values())
    cited = _cited(case.report)
    candidates = [e for e in everything if e.ref in cited] or everything
    if not candidates:
        return []
    failures: list[tuple[Event, set[str], dict[str, str | None]]] = []
    for event in candidates:
        region = event.region_id
        if region is None:  # nationwide: every site is covered
            return []
        venue = _venue_sites(case.reference, event, region)
        outside = _unexplained_sites(case, event, region, venue)
        if not outside:
            return []
        failures.append((event, venue, outside))
    event, venue, outside = min(failures, key=lambda f: len(f[2]))
    where = (
        f"is at {event.node_id} (venue sites: {join_ids(sorted(venue), 8)})"
        if event.node_id
        else f"covers region {event.region_id} (venue sites: every site of {event.region_id})"
    )
    named = ", ".join(f"{s} ({a})" if a else s for s, a in outside.items())
    several = len(outside) > 1
    not_venue = "are not venue sites" if several else "is not a venue site"
    return [
        f"{event.ref} {where}. {named} {not_venue}, so the event does not explain what happened "
        "there. An event explains only its venue sites; judge "
        f"{'them' if several else next(iter(outside))} on {'their' if several else 'its'} own "
        f"evidence, and if {'one of them is' if several else 'it is'} where the reported symptom "
        "is worst the verdict is not expected_event."
    ]


# --- change_timing -----------------------------------------------------------------------------


def _is_rollback(change: Change) -> bool:
    return change.rollback_of is not None or change.change_type.lower() == "rollback"


def _plain(change: Change) -> str:
    """The description without node ids, to tell whether two changes are the same change."""
    text = _NODE_ID.sub("", change.description.upper()).replace(change.node_id, "")
    return " ".join(text.split())


def _nodes_text(nodes: list[str]) -> str:
    return nodes[0] if len(nodes) == 1 else f"{', '.join(nodes[:-1])} and {nodes[-1]}"


def _change_timing(case: _Case) -> list[str]:
    root = case.root
    if case.report.root_cause_category != "bad_change" or not root or not case.facts.changes:
        return []
    candidates = [
        c for c in case.facts.changes.values() if c.node_id == root and not _is_rollback(c)
    ]
    if not candidates:
        return [
            f"bad_change is named on {root}, but no change on {root} is in the tool results; "
            "name the node the change was applied to."
        ]
    reference = case.reference
    scope = {root, *reference.descendants(root), *(_up(a) for a in case.report.affected_node_ids)}
    alerts = sorted(
        (a for a in case.facts.alerts.values() if scope & set(a.entities)),
        key=lambda a: (a.start, a.ref),
    )
    start = _time(case.report.impact_start)
    failing: list[tuple[timedelta, Change, datetime, str | None]] = []
    for change in candidates:
        low, high = change.at - BEFORE, change.at + CHANGE_AFTER
        start_ok = start is None or low <= start <= high
        alerts_ok = not alerts or any(low <= a.start <= high for a in alerts)
        if start_ok and alerts_ok:
            return []
        if not start_ok:
            assert start is not None
            onset = start
            near = min(alerts, key=lambda a: abs(a.start - start), default=None)
        else:
            near = alerts[0]
            onset = near.start
        failing.append((abs(onset - change.at), change, onset, near.ref if near else None))
    _, change, onset, alert_ref = min(failing, key=lambda f: f[0])
    gap = onset - change.at
    when = (
        f"{_minutes(gap)} min later"
        if gap >= timedelta(0)
        else f"{_minutes(-gap)} min before the change"
    )
    text = (
        f"{change.ref} was applied to {root} at {_hm(change.at, onset)}, but the degradation "
        f"began at {_hm(onset, change.at)}{f' ({alert_ref})' if alert_ref else ''}, {when}. "
        "A change takes effect when it lands, so this timing does not support bad_change."
    )
    same = [
        c
        for c in case.facts.changes.values()
        if c.ref != change.ref
        and c.node_id != root
        and not _is_rollback(c)
        and c.change_type == change.change_type
        and abs(c.at - change.at) <= BATCH
        and _plain(c) == _plain(change)
    ]
    nodes = sorted({c.node_id for c in same})
    if nodes:
        text += (
            f" The same change was applied to {_nodes_text(nodes)} at that time; "
            "if they stayed healthy, that is more evidence against it."
        )
    return [text + " Consider a fault of the node itself."]


# --- shared_parent -----------------------------------------------------------------------------


def _shared_parent(case: _Case) -> list[str]:
    root, reference = case.root, case.reference
    if case.report.root_cause_category not in TRANSPORT or not root or len(case.sites) < 2:
        return []
    parent = reference.lowest_common_ancestor(case.sites)
    if parent is None or root == parent:
        return []
    is_site = reference.node_type.get(root) == "site"
    if not is_site and any(a.node_id == root for a in case.facts.alarms.values()):
        return []
    sites = join_ids(list(case.sites), 8)
    share = f"The affected sites {sites} share {parent} as their lowest common parent"
    if is_site and reference.parent_of.get(root) == parent:
        return [
            f"{share}, and {root} is one of them, not their parent. A fault at one site would "
            f"not take down the others; name {parent} (or a node above it that carries an "
            "alarm) as the root cause node."
        ]
    if root in reference.ancestors(parent):
        return [
            f"{share} and no alarm sits on {root}. A failure of {root} would also have hit its "
            f"other children; without a signal of its own there, name {parent} as the root "
            "cause node."
        ]
    # A root beside the shared parent (sites under two links, one link named) is left alone: two
    # separate things may have happened, and the shared parent would be the wrong advice.
    return []


# --- planned_outage ----------------------------------------------------------------------------


def _planned_outage(case: _Case) -> list[str]:
    root, reference = case.root, case.reference
    if case.report.classification != "incident" or not root:
        return []
    below = {root, *reference.descendants(root)}
    holders = {root, *reference.ancestors(root)}
    for window in sorted(case.facts.windows.values(), key=lambda w: (w.start, w.ref)):
        if window.node_id not in holders or not _has_impact(window):
            continue
        alarms = _outage_alarms(case, below, window)
        if not alarms or any(any(_alarm_gaps(case, a, window)) for a in alarms):
            continue
        alarms.sort(key=lambda a: (a.raised, a.ref))
        cleared = [a.cleared for a in alarms]
        ended = None if None in cleared else max(c for c in cleared if c is not None)
        return [
            f"The outage under {root} ({', '.join(a.ref for a in alarms)}, "
            f"{_span(alarms[0].raised, ended)}) lies inside maintenance window {window.ref} on "
            f"{window.node_id} ({_span(window.start, window.end)}, expected impact: "
            f"{window.expected_impact.strip()}). That is planned work, not an incident. If "
            "other nodes failed outside any window, the incident is there: name that node and "
            "its cause; otherwise the verdict is planned_maintenance."
        ]
    return []


_RUNNERS: dict[str, Callable[[_Case], list[str]]] = {
    "maintenance_window": _maintenance_window,
    "event_venue": _event_venue,
    "change_timing": _change_timing,
    "shared_parent": _shared_parent,
    "planned_outage": _planned_outage,
}


def lookalike_problems(
    report: Report,
    facts: Facts,
    reference: Reference,
    asked_at: datetime,
    enabled: Sequence[str] = CHECKS,
) -> list[str]:
    """What the fetched records contradict in `report`, as sentences (at most four)."""
    root = _up(report.root_cause_node_id) or None
    case = _Case(
        report, facts, reference, as_utc(asked_at), root, _affected_sites(report, root, reference)
    )
    problems: list[str] = []
    for name in CHECKS:
        if name in enabled:
            problems += _RUNNERS[name](case)
    return problems[:MAX_PROBLEMS]
