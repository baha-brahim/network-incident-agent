"""Deterministic checks of a report against the evidence the run actually gathered."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from incident_agent.agent.reference import Reference
from incident_agent.agent.report import (
    CLASSIFICATION_OF,
    DismissedSignal,
    Finding,
    HypothesisEntry,
    Report,
    TimelineEntry,
)
from incident_agent.agent.state import CallRecord
from incident_agent.agent.tools.timeutil import TimeParseError, as_utc, fmt, parse_time
from incident_agent.agent.types import EvidenceRef

_WRAP = re.compile(r"[\s`'\"\[\]()]")


def canonical_ref(raw: str, known: dict[str, str]) -> str | None:
    """The registry spelling of `raw` (case, brackets and spaces ignored), or None."""
    key = _WRAP.sub("", raw).upper()
    return known.get(key)


def _lookup(evidence: dict[str, EvidenceRef], reference: Reference) -> dict[str, str]:
    table = {k.upper(): k for k in evidence}
    for node in (*reference.node_ids, *reference.cell_ids, *reference.regions):
        table.setdefault(node.upper(), node)
    return table


@dataclass
class Checked:
    report: Report
    problems: list[str]


def _local_time(value: str | None, label: str, asked_at: datetime, problems: list[str]) -> None:
    if value is None:
        return
    try:
        parsed = parse_time(value, name=label)
    except TimeParseError:
        problems.append(f"{label} {value!r} is not a time like 2026-09-21 16:50.")
        return
    if parsed > as_utc(asked_at):
        problems.append(f"{label} {value} is after now ({fmt(asked_at)}).")


def normalise_refs(
    report: Report, evidence: dict[str, EvidenceRef], reference: Reference
) -> tuple[Report, list[str]]:
    """Rewrite refs to their registry spelling. Returns the report and the refs that don't exist."""
    table = _lookup(evidence, reference)
    unknown: list[str] = []

    def fix(refs: list[str]) -> list[str]:
        out: list[str] = []
        for raw in refs:
            found = canonical_ref(raw, table)
            if found is None:
                unknown.append(raw)
            elif found not in out:
                out.append(found)
        return out

    fixed = report.model_copy(
        update={
            "timeline": [t.model_copy(update={"refs": fix(t.refs)}) for t in report.timeline],
            "findings": [f.model_copy(update={"refs": fix(f.refs)}) for f in report.findings],
            "hypotheses": [h.model_copy(update={"refs": fix(h.refs)}) for h in report.hypotheses],
            "dismissed_signals": _fix_dismissed(report.dismissed_signals, table, unknown),
        }
    )
    return fixed, unknown


def _fix_dismissed(
    items: list[DismissedSignal], table: dict[str, str], unknown: list[str]
) -> list[DismissedSignal]:
    out = []
    for item in items:
        found = canonical_ref(item.ref, table)
        if found is None:
            unknown.append(item.ref)
        else:
            out.append(item.model_copy(update={"ref": found}))
    return out


def check_report(
    original: Report,
    evidence: dict[str, EvidenceRef],
    reference: Reference,
    asked_at: datetime,
) -> Checked:
    """Normalise refs, then list everything wrong with the report."""
    report, unknown = normalise_refs(original, evidence, reference)
    problems: list[str] = []
    if unknown:
        shown = ", ".join(dict.fromkeys(unknown))
        problems.append(
            f"These references do not exist in the case file: {shown}. Cite only listed ones."
        )
    for n, finding in enumerate(report.findings, 1):
        if not finding.refs:
            problems.append(f"Finding {n} has no valid reference: {finding.claim[:80]!r}.")
    node = report.root_cause_node_id
    if node is not None and node.strip().upper() not in reference.node_ids:
        problems.append(f"root_cause_node_id {node!r} is not a node of this network.")
    for affected in report.affected_node_ids:
        if not reference.known(affected.strip().upper()):
            problems.append(f"affected_node_ids contains {affected!r}, which does not exist.")
    expected = CLASSIFICATION_OF[report.root_cause_category]
    if report.classification != expected:
        problems.append(
            f"classification {report.classification} does not match root_cause_category "
            f"{report.root_cause_category} (expected {expected})."
        )
    _local_time(report.impact_start, "impact_start", asked_at, problems)
    _local_time(report.impact_end, "impact_end", asked_at, problems)
    _local_time(report.root_cause_time, "root_cause_time", asked_at, problems)
    for entry in report.timeline:
        _local_time(entry.time, "timeline time", asked_at, problems)
    return Checked(report, problems[:8])


def strip_invalid(
    report: Report, reference: Reference, asked_at: datetime
) -> tuple[Report, list[str]]:
    """Last resort: remove what cannot be defended. Returns the report and what was removed.

    Refs were already normalised (unknown ones are gone). Findings left without a ref are dropped.
    """
    notes: list[str] = []
    findings = [f for f in report.findings if f.refs]
    if len(findings) < len(report.findings):
        notes.append(
            f"Removed {len(report.findings) - len(findings)} finding(s) without a valid reference."
        )

    def valid_time(value: str | None, label: str) -> str | None:
        if value is None:
            return None
        try:
            ok = parse_time(value) <= as_utc(asked_at)
        except TimeParseError:
            ok = False
        if not ok:
            notes.append(f"Removed invalid {label} {value!r}.")
        return value if ok else None

    timeline: list[TimelineEntry] = []
    for entry in report.timeline:
        if valid_time(entry.time, "timeline time") is not None:
            timeline.append(entry)
    update: dict[str, object] = {
        "findings": findings,
        "timeline": timeline,
        "impact_start": valid_time(report.impact_start, "impact_start"),
        "impact_end": valid_time(report.impact_end, "impact_end"),
        "root_cause_time": valid_time(report.root_cause_time, "root_cause_time"),
        "affected_node_ids": [
            a for a in report.affected_node_ids if reference.known(a.strip().upper())
        ],
    }
    node = report.root_cause_node_id
    if node is not None and node.strip().upper() not in reference.node_ids:
        notes.append(f"Removed unknown root_cause_node_id {node!r}.")
        update["root_cause_node_id"] = None
        update["confidence"] = "low"
    cleaned = report.model_copy(update=update)
    expected = CLASSIFICATION_OF[cleaned.root_cause_category]
    if cleaned.classification != expected:
        notes.append(
            f"classification {cleaned.classification} contradicts category "
            f"{cleaned.root_cause_category}; set to inconclusive."
        )
        cleaned = cleaned.model_copy(update={"classification": "inconclusive", "confidence": "low"})
    return cleaned, notes


def _sources(
    refs: list[str], evidence: dict[str, EvidenceRef], tool_of: dict[str, str]
) -> set[str]:
    """Distinct kinds of evidence behind a set of refs: row kinds, and tool names for call refs."""
    out: set[str] = set()
    for ref in refs:
        known = evidence.get(ref)
        if known is None or known.kind == "node":
            continue
        out.add(f"tool:{tool_of.get(ref, '?')}" if known.kind == "call" else known.kind)
    return out


def cap_confidence(
    report: Report,
    evidence: dict[str, EvidenceRef],
    tool_of: dict[str, str],
    missing_checks: list[str],
) -> tuple[Report, list[str]]:
    """Lower an over-confident report.

    High needs two kinds of evidence and the lookalike checks. "No impact" needs something that
    positively explains the question (alarms, an alert, a record); an empty search proves little.
    """
    if report.confidence == "low":
        return report, []
    cited = [r for f in report.findings for r in f.refs] + [
        r for h in report.hypotheses if h.verdict == "confirmed" for r in h.refs
    ]
    cited_kinds = {evidence[r].kind for r in cited if r in evidence}
    positive = {"alarm", "alert", "anomaly", "event", "change", "maintenance"}
    if report.classification == "no_impact" and not cited_kinds & positive:
        note = (
            "Confidence lowered to low: nothing positive explains the report (symptom not found)."
        )
        return report.model_copy(update={"confidence": "low"}), [note]
    if report.confidence != "high":
        return report, []
    reasons: list[str] = []
    if report.classification == "inconclusive":
        reasons.append("the conclusion is inconclusive")
    if report.classification == "incident":
        if missing_checks:
            reasons.append(f"not checked: {', '.join(missing_checks)}")
        if len(_sources(cited, evidence, tool_of)) < 2:
            reasons.append("fewer than two kinds of evidence are cited")
    wanted = {"planned_maintenance": "maintenance", "expected_event": "event"}
    kind = wanted.get(report.classification)
    if kind and kind not in cited_kinds:
        reasons.append(f"no {kind} record is cited")
    if not reasons:
        return report, []
    lowered = "low" if report.classification == "inconclusive" else "medium"
    note = f"Confidence lowered from high to {lowered}: {'; '.join(reasons)}."
    return report.model_copy(update={"confidence": lowered}), [note]


# What a claim of absence must be backed by: the tool that looks for the thing.
_ABSENCE: dict[str, tuple[str, re.Pattern[str]]] = {
    tool: (label, re.compile(rf"\bno\b[^.;,]{{0,40}}?\b(?:{words})\b", re.IGNORECASE))
    for tool, label, words in (
        ("get_changes", "changes", r"changes|change records?|change log"),
        ("get_maintenance", "maintenance", "maintenance"),
        ("get_external_events", "external events", r"external events?|events?|holidays?"),
        ("get_alarms", "alarms", r"alarms?"),
    )
}
_ROW_KINDS = {"alarm", "change", "maintenance", "event", "anomaly", "alert"}


def _flatten(value: object) -> list[str]:
    if isinstance(value, list | tuple):
        return [s for v in value for s in _flatten(v)]
    return [str(value).strip().upper()] if value not in (None, "") else []


def _mentions(text: str, node: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(node)}(?![\w-])", text, re.IGNORECASE) is not None


def _evidence_about(
    node: str, refs: list[str], evidence: dict[str, EvidenceRef], calls: Sequence[CallRecord]
) -> bool:
    """True if one of the cited refs is a record or a (non-topology) call about `node`."""
    by_ref = {c.ref: c for c in calls}
    for ref in refs:
        known = evidence.get(ref)
        if known is not None and known.kind in _ROW_KINDS and _mentions(known.summary, node):
            return True
        call = by_ref.get(ref)
        if call and call.tool != "get_topology" and node in _flatten(list(call.args.values())):
            return True
    return False


def check_faithfulness(
    report: Report,
    evidence: dict[str, EvidenceRef],
    calls: Sequence[CallRecord],
    reference: Reference,
) -> tuple[Report, list[str]]:
    """Cheap checks of what the report claims against what it cites. Returns notes, not repairs.

    - A claim of absence ("no changes", "no alarms", ...) must cite a call of the tool that looks.
    - A root cause named on a parent of every affected node needs cited evidence about that
      parent; without it confidence is capped at medium.
    """
    notes: list[str] = []
    checked = {c.ref: c.tool for c in calls if not c.error}
    for n, finding in enumerate(report.findings, 1):
        for tool, (label, pattern) in _ABSENCE.items():
            if pattern.search(finding.claim) and not any(
                checked.get(r) == tool for r in finding.refs
            ):
                notes.append(
                    f"Finding {n} claims no {label} but cites no {tool} call: "
                    f"{finding.claim[:70]!r}."
                )
    node = (report.root_cause_node_id or "").strip().upper()
    affected = [a.strip().upper() for a in report.affected_node_ids]
    if node and affected and all(node in reference.ancestors(a) for a in affected):
        cited = (
            [r for t in report.timeline for r in t.refs]
            + [r for f in report.findings for r in f.refs]
            + [r for h in report.hypotheses if h.verdict == "confirmed" for r in h.refs]
        )
        if not _evidence_about(node, cited, evidence, calls):
            notes.append(
                f"Root cause {node} is a parent of every affected node, but no cited evidence is "
                "about it (its own alarm, change, maintenance or KPI)."
            )
            if report.confidence == "high":
                report = report.model_copy(update={"confidence": "medium"})
                notes[-1] += " Confidence lowered from high to medium."
    return report, notes


__all__ = [
    "Checked",
    "DismissedSignal",
    "Finding",
    "HypothesisEntry",
    "cap_confidence",
    "check_faithfulness",
    "check_report",
    "normalise_refs",
    "strip_invalid",
]
