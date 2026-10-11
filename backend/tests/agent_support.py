"""Shared helpers of the agent tests: a canned tool executor, a reference, report builders."""

from typing import Any

from incident_agent.agent.reference import Reference
from incident_agent.agent.report import Finding, HypothesisEntry, Report, TimelineEntry
from incident_agent.agent.types import EvidenceRef, ToolContext, ToolResult
from incident_agent.llm.testing import RecordedCall
from incident_agent.llm.types import ToolCall

REFERENCE = Reference(
    regions={"TUN": "Grand Tunis", "SFX": "Sfax"},
    node_ids={"S-TUN-001", "S-TUN-002", "LNK-TUN-01-A", "AGG-TUN-01", "CORE-DNS-01", "S-SFX-001"},
    cell_ids={"C-TUN-001-1"},
    id_formats=["site S-<REGION>-nnn"],
    core_nodes=["CORE-DNS-01"],
)

WINDOW = {"start": "2026-09-02 08:00", "end": "2026-09-02 12:00"}

_ROWS: dict[str, tuple[str, str, str]] = {
    "get_alarms": ("ALM-000001", "alarm", "critical LINK_LOS on LNK-TUN-01-A raised 09:00, active"),
    "get_maintenance": ("MW-0001", "maintenance", "battery swap on S-SFX-001"),
    "get_changes": ("CHG-2026-0002", "change", "config_push on AGG-TUN-01"),
    "get_external_events": ("EVT-001", "event", "stadium_event near S-TUN-003"),
    "get_anomalies": ("ALR-0001", "alert", "availability drop on 2 sites"),
    "get_topology": ("LNK-TUN-01-A", "node", "fiber link below AGG-TUN-01"),
    "search_runbooks": ("RB-FIBER-CUT#03", "runbook", "Differential diagnosis"),
}


def fake_tools(name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Canned results: one citable row per tool, a headline, a body of a few hundred characters."""
    if name not in _ROWS:
        return ToolResult(
            tool=name,
            args=args,
            headline=f"{name} error: unknown tool",
            body=f"Unknown tool {name!r}.",
            error=f"Unknown tool {name!r}.",
        )
    ref, kind, summary = _ROWS[name]
    return ToolResult(
        tool=name,
        args=args,
        headline=f"{name}: 1 row ({summary})",
        body=f"{name} result.\n{ref} {summary}\n" + "detail line. " * 20,
        refs=[EvidenceRef(ref=ref, kind=kind, summary=summary)],  # type: ignore[arg-type]
    )


INTAKE = {
    "symptom": "traffic drop",
    "window_start": "2026-09-02 08:00",
    "window_end": "2026-09-02 12:00",
    "region_ids": ["TUN"],
    "node_ids": ["S-TUN-001"],
    "nationwide": False,
    "ongoing": False,
}


def make_report(**over: Any) -> Report:
    base: dict[str, Any] = {
        "title": "Fiber cut on LNK-TUN-01-A",
        "classification": "incident",
        "root_cause_category": "transport_failure",
        "root_cause_node_id": "LNK-TUN-01-A",
        "root_cause_summary": "The link lost light and took two sites down.",
        "confidence": "high",
        "confidence_reason": "Alarm on the link precedes the outage; calendar and events checked.",
        "impact_summary": "Two sites down for four hours.",
        "impact_start": "2026-09-02 09:00",
        "impact_end": None,
        "root_cause_time": "2026-09-02 09:00",
        "affected_node_ids": ["S-TUN-001", "S-TUN-002"],
        "timeline": [
            TimelineEntry(time="2026-09-02 09:00", event="LOS on the link", refs=["ALM-000001"])
        ],
        "findings": [
            Finding(claim="Critical LOS on the link", basis="observed", refs=["ALM-000001"]),
            Finding(claim="Window MW-0001 is on another site", basis="observed", refs=["MW-0001"]),
        ],
        "hypotheses": [
            HypothesisEntry(
                category="transport_failure",
                node_id="LNK-TUN-01-A",
                verdict="confirmed",
                reason="alarm and timing fit",
                refs=["ALM-000001"],
            )
        ],
        "dismissed_signals": [],
        "recommended_actions": ["Dispatch a field team to the link."],
    }
    return Report.model_validate(base | over)


def script_for(
    turns: list[list[ToolCall] | str],
    report: Report | list[Report] | None = None,
    intake: dict[str, Any] | None = None,
):  # type: ignore[no-untyped-def]
    """A ScriptedRunner script: intake, then the given investigate turns, then reports."""
    reports = [report] if isinstance(report, Report) else list(report or [make_report()])
    state = {"turn": 0, "report": 0}

    def script(call: RecordedCall) -> Any:
        if call.purpose == "intake":
            return intake or INTAKE
        if call.purpose.startswith("investigate"):
            item = turns[min(state["turn"], len(turns) - 1)]
            state["turn"] += 1
            return item
        item = reports[min(state["report"], len(reports) - 1)]
        state["report"] += 1
        return item

    return script
