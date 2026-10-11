"""The incident report: a flat structured output, and its markdown rendering."""

from typing import Literal

from pydantic import BaseModel, Field

from incident_agent.agent.types import EvidenceRef

Classification = Literal[
    "incident", "planned_maintenance", "expected_event", "no_impact", "inconclusive"
]
Category = Literal[
    "transport_failure",
    "power_failure",
    "bad_change",
    "core_degradation",
    "capacity",
    "transport_degradation",
    "planned_maintenance",
    "expected_event",
    "no_impact",
    "unknown",
]
Confidence = Literal["low", "medium", "high"]

INCIDENT_CATEGORIES = {
    "transport_failure",
    "power_failure",
    "bad_change",
    "core_degradation",
    "capacity",
    "transport_degradation",
}
# The classification each category implies.
CLASSIFICATION_OF: dict[str, str] = {
    **dict.fromkeys(INCIDENT_CATEGORIES, "incident"),
    "planned_maintenance": "planned_maintenance",
    "expected_event": "expected_event",
    "no_impact": "no_impact",
    "unknown": "inconclusive",
}


# Most entries a report keeps per section; the schema tells the model, `limit_report` enforces it.
MAX_TIMELINE = 8
MAX_FINDINGS = 6
MAX_HYPOTHESES = 4
MAX_DISMISSED = 5
MAX_ACTIONS = 4


class TimelineEntry(BaseModel):
    time: str = Field(description="Local time, YYYY-MM-DD HH:MM")
    event: str = Field(description="At most 20 words.")
    refs: list[str]


class Finding(BaseModel):
    claim: str = Field(description="One fact, at most 30 words.")
    basis: Literal["observed", "inferred"] = Field(
        description="observed: a cited tool result shows it. inferred: your reasoning from it."
    )
    refs: list[str]


class HypothesisEntry(BaseModel):
    category: Category
    node_id: str | None
    verdict: Literal["confirmed", "rejected", "unresolved"]
    reason: str = Field(description="At most 30 words.")
    refs: list[str]


class DismissedSignal(BaseModel):
    ref: str
    reason: str = Field(description="At most 30 words.")


class Report(BaseModel):
    title: str = Field(description="At most 12 words.")
    classification: Classification
    root_cause_category: Category
    root_cause_node_id: str | None
    root_cause_summary: str = Field(description="Cause and mechanism, at most 40 words.")
    confidence: Confidence
    confidence_reason: str = Field(
        description="What supports the confidence level or limits it, at most 30 words."
    )
    impact_summary: str = Field(description="At most 30 words.")
    impact_start: str | None = Field(description="Local time, YYYY-MM-DD HH:MM")
    impact_end: str | None = Field(
        description="Local time the impact stopped; null if ongoing or unknown"
    )
    root_cause_time: str | None = Field(description="Local time of the cause, if known")
    affected_node_ids: list[str]
    timeline: list[TimelineEntry] = Field(description=f"At most {MAX_TIMELINE} entries.")
    findings: list[Finding] = Field(
        description=f"At most {MAX_FINDINGS}; do not repeat a fact stated elsewhere."
    )
    hypotheses: list[HypothesisEntry] = Field(
        description=f"At most {MAX_HYPOTHESES}, ranked, most likely first."
    )
    dismissed_signals: list[DismissedSignal] = Field(description=f"At most {MAX_DISMISSED}.")
    recommended_actions: list[str] = Field(
        description=f"At most {MAX_ACTIONS}, each under 25 words."
    )


def limit_report(report: Report) -> tuple[Report, list[str]]:
    """Cut every section to its maximum; returns the report and a note for each cut."""
    caps = {
        "timeline": MAX_TIMELINE,
        "findings": MAX_FINDINGS,
        "hypotheses": MAX_HYPOTHESES,
        "dismissed_signals": MAX_DISMISSED,
        "recommended_actions": MAX_ACTIONS,
    }
    update: dict[str, object] = {}
    notes: list[str] = []
    for name, cap in caps.items():
        items = getattr(report, name)
        if len(items) > cap:
            update[name] = items[:cap]
            notes.append(f"Report cut to {cap} {name.replace('_', ' ')} (had {len(items)}).")
    return (report.model_copy(update=update) if update else report), notes


PARTIAL_PREFIX = "partial report:"


def is_partial(issues: list[str]) -> bool:
    return any(i.startswith(PARTIAL_PREFIX) for i in issues)


def all_refs(report: Report) -> list[str]:
    refs: list[str] = []
    for entry in report.timeline:
        refs += entry.refs
    for finding in report.findings:
        refs += finding.refs
    for hyp in report.hypotheses:
        refs += hyp.refs
    refs += [d.ref for d in report.dismissed_signals]
    return refs


def fallback_report(reason: str, findings: list[Finding]) -> Report:
    """What is returned when no model could write the report: inconclusive, low confidence."""
    return Report(
        title="Investigation incomplete",
        classification="inconclusive",
        root_cause_category="unknown",
        root_cause_node_id=None,
        root_cause_summary=f"No conclusion could be written: {reason}",
        confidence="low",
        confidence_reason="The report could not be produced; the notes below are raw call results.",
        impact_summary="Unknown.",
        impact_start=None,
        impact_end=None,
        root_cause_time=None,
        affected_node_ids=[],
        timeline=[],
        findings=findings,
        hypotheses=[],
        dismissed_signals=[],
        recommended_actions=["Re-run the investigation, or review the tool results manually."],
    )


def _refs(refs: list[str]) -> str:
    return f" [{', '.join(refs)}]" if refs else ""


def render_markdown(
    report: Report,
    evidence: dict[str, EvidenceRef],
    *,
    issues: list[str] | None = None,
) -> str:
    """The report as markdown, with an appendix that spells out every cited reference."""
    r = report
    ongoing = "not established or ongoing" if r.impact_end is None else r.impact_end
    lines = [f"# {r.title}", ""]
    if is_partial(issues or []):
        lines += [
            "> **Partial report.** The full answer could not be read; only the core fields were "
            "recovered and confidence is forced to low.",
            "",
        ]
    lines += [
        f"- **Classification:** {r.classification}",
        f"- **Root cause:** {r.root_cause_category}"
        + (f" at `{r.root_cause_node_id}`" if r.root_cause_node_id else ""),
        f"- **Confidence:** {r.confidence} ({r.confidence_reason})",
        f"- **Impact:** {r.impact_start or 'unknown start'} to {ongoing}",
    ]
    if r.root_cause_time:
        lines.append(f"- **Cause time:** {r.root_cause_time}")
    if r.affected_node_ids:
        lines.append(f"- **Affected:** {', '.join(r.affected_node_ids)}")
    lines += ["", "## Summary", "", r.root_cause_summary, "", r.impact_summary]
    if r.timeline:
        lines += ["", "## Timeline", ""]
        lines += [f"- {t.time}: {t.event}{_refs(t.refs)}" for t in r.timeline]
    for basis, heading in (("observed", "Evidence"), ("inferred", "Inferences")):
        items = [f for f in r.findings if f.basis == basis]
        if items:
            lines += ["", f"## {heading}", ""]
            lines += [f"- {f.claim}{_refs(f.refs)}" for f in items]
    if r.hypotheses:
        lines += ["", "## Hypotheses", ""]
        for n, h in enumerate(r.hypotheses, 1):
            where = f" at {h.node_id}" if h.node_id else ""
            lines.append(f"{n}. **{h.category}**{where}: {h.verdict}. {h.reason}{_refs(h.refs)}")
    if r.dismissed_signals:
        lines += ["", "## Ruled out", ""]
        lines += [f"- {d.ref}: {d.reason}" for d in r.dismissed_signals]
    if r.recommended_actions:
        lines += ["", "## Recommended actions", ""]
        lines += [f"- {a}" for a in r.recommended_actions]
    cited = list(dict.fromkeys(all_refs(r)))
    if cited:
        lines += ["", "## Sources", ""]
        for ref in cited:
            known = evidence.get(ref)
            lines.append(f"- `{ref}`: {known.summary if known else 'not in the evidence registry'}")
    if issues:
        lines += ["", "## Verification notes", ""] + [f"- {i}" for i in issues]
    return "\n".join(lines) + "\n"
