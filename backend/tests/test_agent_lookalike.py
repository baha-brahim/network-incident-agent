"""The look-alike stage of the verify step in the graph: scripted model, canned tools."""

from dataclasses import replace
from typing import Any

from sqlalchemy import create_engine

from incident_agent.agent import AgentConfig, investigate
from incident_agent.agent.report import Finding
from incident_agent.agent.state import AgentEvent
from incident_agent.agent.tools.timeutil import iso, parse_time
from incident_agent.agent.types import ToolContext, ToolResult
from incident_agent.llm.testing import RecordedCall, ScriptedRunner
from incident_agent.llm.types import ToolCall
from tests.agent_support import REFERENCE, WINDOW, fake_tools, make_report, script_for

ASKED = parse_time("2026-09-02 12:00")
CTX = ToolContext(engine=create_engine("sqlite://"), asked_at=ASKED)
CHECKS = [
    [ToolCall(name=t, args=dict(WINDOW)) for t in ("get_alarms", "get_maintenance", "get_changes")],
    [ToolCall(name="get_external_events", args=dict(WINDOW))],
    "done",
]

TOPOLOGY = replace(
    REFERENCE,
    parent_of={
        "S-TUN-001": "LNK-TUN-01-A",
        "S-TUN-002": "LNK-TUN-01-A",
        "LNK-TUN-01-A": "AGG-TUN-01",
    },
    node_type={
        "S-TUN-001": "site",
        "S-TUN-002": "site",
        "LNK-TUN-01-A": "transport_link",
        "AGG-TUN-01": "agg_router",
    },
    region_of={"S-TUN-001": "TUN", "S-TUN-002": "TUN"},
)

# The link is cut at 09:00 and repaired at 10:00, inside a window on it that runs 08:30 to 10:30.
ROWS: dict[str, dict[str, Any]] = {
    "get_alarms": {
        "rows": [
            {
                "alarm_id": "ALM-000001",
                "node_id": "LNK-TUN-01-A",
                "alarm_type": "LINK_LOS",
                "severity": "critical",
                "raised_at": iso(parse_time("2026-09-02 09:00")),
                "cleared_at": iso(parse_time("2026-09-02 10:00")),
            }
        ]
    },
    "get_maintenance": {
        "rows": [
            {
                "mw_id": "MW-0001",
                "node_id": "LNK-TUN-01-A",
                "start_at": iso(parse_time("2026-09-02 08:30")),
                "end_at": iso(parse_time("2026-09-02 10:30")),
                "description": "Splicing",
                "expected_impact": "Downstream sites offline",
            }
        ]
    },
}


def tools_with_rows(name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    result = fake_tools(name, args, ctx)
    return result.model_copy(update={"data": ROWS[name]}) if name in ROWS else result


def run(script: Any, config: AgentConfig | None = None, tools: Any = tools_with_rows) -> Any:
    runner = ScriptedRunner(script)
    result = investigate(
        "Why did traffic drop at S-TUN-001?",
        ASKED,
        runner=runner,
        ctx=CTX,
        config=config,
        reference=TOPOLOGY,
        tool_executor=tools,
    )
    return result, runner


# The model calls an outage inside a planned window an incident, and the checks say so.
INCIDENT = make_report(impact_start="2026-09-02 09:00", impact_end="2026-09-02 10:00")
PLANNED = make_report(
    title="Planned splicing on LNK-TUN-01-A",
    classification="planned_maintenance",
    root_cause_category="planned_maintenance",
    impact_start="2026-09-02 09:00",
    impact_end="2026-09-02 10:00",
    findings=[
        Finding(claim="Window MW-0001 covers the link", basis="observed", refs=["MW-0001"]),
        Finding(claim="The link alarm lies inside it", basis="observed", refs=["ALM-000001"]),
    ],
    hypotheses=[],
)


def purposes(runner: ScriptedRunner) -> list[str]:
    return [c.purpose for c in runner.calls]


def lookalike_issues(result: Any, prefix: str) -> list[str]:
    return [i for i in result.issues if i.startswith(prefix)]


def test_a_failing_check_costs_one_call_and_the_corrected_report_is_returned() -> None:
    result, runner = run(script_for(CHECKS, [INCIDENT, PLANNED]))
    assert purposes(runner)[-2:] == ["conclude", "lookalike repair 1"]
    assert purposes(runner).count("lookalike repair 1") == 1
    repair = runner.calls[-1]
    assert "MW-0001" in repair.prompt and "ALM-000001" in repair.prompt
    assert "Checks of your report against the records" in repair.prompt
    assert repair.max_output_tokens == 3072
    assert INCIDENT.root_cause_summary in repair.prompt  # the previous report is in it
    assert result.report.classification == "planned_maintenance"
    assert result.report_before_checks == INCIDENT.model_copy(
        update={"confidence": result.report_before_checks.confidence}
    )
    assert result.report_before_checks.classification == "incident"
    found = lookalike_issues(result, "[lookalike] ")
    assert len(found) == 1 and "lies inside maintenance window MW-0001" in found[0]
    assert not lookalike_issues(result, "lookalike unresolved: ")
    assert result.status == "finished"
    assert "repair 1" not in purposes(runner)  # nothing was wrong with the citations


def test_a_report_that_still_fails_ends_low_with_the_problem_listed() -> None:
    result, runner = run(script_for(CHECKS, [INCIDENT, INCIDENT]))
    assert purposes(runner)[-2:] == ["conclude", "lookalike repair 1"]
    assert result.report.classification == "incident"
    assert result.report.confidence == "low"
    assert result.report_before_checks is not None
    assert result.report_before_checks.confidence != "low"
    unresolved = lookalike_issues(result, "lookalike unresolved: ")
    assert len(unresolved) == 1 and "MW-0001" in unresolved[0]
    assert any(i.startswith("Confidence set to low") for i in result.issues)
    assert "lookalike unresolved: " in result.markdown


def test_a_corrected_report_that_cites_nothing_real_is_stripped_not_asked_again() -> None:
    bad_refs = PLANNED.model_copy(
        update={"findings": [Finding(claim="Made up", basis="observed", refs=["ALM-999999"])]}
    )
    result, runner = run(script_for(CHECKS, [INCIDENT, bad_refs]))
    assert purposes(runner).count("lookalike repair 1") == 1 and "repair 1" not in purposes(runner)
    assert any(i.startswith("unresolved: ") for i in result.issues)
    assert result.report.classification == "planned_maintenance"
    assert result.report.findings == []


def test_with_the_checks_off_there_is_no_extra_call() -> None:
    result, runner = run(script_for(CHECKS, [INCIDENT]), AgentConfig(lookalike_checks=()))
    assert purposes(runner)[-1] == "conclude"
    assert result.report_before_checks is None
    assert result.report.classification == "incident"
    assert not [i for i in result.issues if "lookalike" in i.lower()]


def test_without_repairs_the_confidence_is_capped_and_no_call_is_made() -> None:
    result, runner = run(
        script_for(CHECKS, [INCIDENT, PLANNED]), AgentConfig(max_lookalike_repairs=0)
    )
    assert purposes(runner)[-1] == "conclude"
    assert result.report.confidence == "low" and result.report.classification == "incident"
    assert result.report_before_checks is not None
    assert len(lookalike_issues(result, "lookalike unresolved: ")) == 1
    assert not lookalike_issues(result, "[lookalike] ")


def test_a_report_that_passes_costs_nothing() -> None:
    result, runner = run(script_for(CHECKS, [PLANNED]))
    assert purposes(runner)[-1] == "conclude"
    assert result.report_before_checks is None
    assert result.report.classification == "planned_maintenance"
    assert not [i for i in result.issues if "lookalike" in i.lower()]


def test_a_failed_repair_call_keeps_the_earlier_report_at_low_confidence() -> None:
    base = script_for(CHECKS, [INCIDENT])

    def script(call: RecordedCall) -> Any:
        if call.purpose.startswith("lookalike repair"):
            return RuntimeError("quota exhausted")
        return base(call)

    result, runner = run(script)
    assert purposes(runner)[-1] == "lookalike repair 1"
    assert result.report.classification == "incident" and result.report.confidence == "low"
    failed = lookalike_issues(result, "lookalike repair call failed: ")
    assert len(failed) == 1 and "quota exhausted" in failed[0]
    assert len(lookalike_issues(result, "lookalike unresolved: ")) == 1
    assert result.status == "finished" and result.error is None
    assert any(s.error for s in result.steps)


def test_more_repairs_can_be_allowed() -> None:
    result, runner = run(
        script_for(CHECKS, [INCIDENT, INCIDENT, PLANNED]), AgentConfig(max_lookalike_repairs=2)
    )
    assert purposes(runner)[-3:] == ["conclude", "lookalike repair 1", "lookalike repair 2"]
    assert result.report.classification == "planned_maintenance"
    assert len(lookalike_issues(result, "[lookalike] ")) == 2


def test_rows_of_a_failed_call_are_not_facts() -> None:
    def failing(name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        result = tools_with_rows(name, args, ctx)
        if name == "get_maintenance":
            return result.model_copy(update={"error": "boom"})
        return result

    result, runner = run(script_for(CHECKS, [INCIDENT]), tools=failing)
    assert purposes(runner)[-1] == "conclude"  # no window known, so nothing to contradict
    assert result.report_before_checks is None


def test_a_repeated_call_adds_no_second_copy_of_the_rows() -> None:
    twice = [
        [ToolCall(name="get_maintenance", args=dict(WINDOW))] * 2,
        [ToolCall(name="get_alarms", args=dict(WINDOW))],
        "done",
    ]
    result, runner = run(script_for(twice, [INCIDENT, PLANNED]))
    assert purposes(runner).count("lookalike repair 1") == 1
    assert result.report.classification == "planned_maintenance"


def test_the_corrected_report_is_the_one_in_the_final_event() -> None:
    events: list[AgentEvent] = []
    runner = ScriptedRunner(script_for(CHECKS, [INCIDENT, PLANNED]))
    investigate(
        "Why did traffic drop at S-TUN-001?",
        ASKED,
        runner=runner,
        ctx=CTX,
        reference=TOPOLOGY,
        tool_executor=tools_with_rows,
        on_event=events.append,
    )
    reports = [e for e in events if e.type == "report"]
    assert (
        len(reports) == 1 and reports[0].data["report"]["classification"] == "planned_maintenance"
    )
