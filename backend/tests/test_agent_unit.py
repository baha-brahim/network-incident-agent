"""Agent graph tests with a scripted runner and canned tools: no database, no network."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine

from incident_agent.agent import AgentConfig, investigate, stream
from incident_agent.agent.casefile import render_case_file, render_registry
from incident_agent.agent.nodes import Deps, IntakeOutput, build_scope, missing_checks
from incident_agent.agent.reference import id_pattern
from incident_agent.agent.report import Finding, fallback_report, render_markdown
from incident_agent.agent.state import AgentEvent, AgentState, CallRecord, Note, Scope
from incident_agent.agent.tools.timeutil import parse_time
from incident_agent.agent.types import EvidenceRef, ToolContext
from incident_agent.agent.verify import cap_confidence, check_report, strip_invalid
from incident_agent.llm.testing import RecordedCall, ScriptedRunner
from incident_agent.llm.types import ToolCall
from tests.agent_support import REFERENCE, WINDOW, fake_tools, make_report, script_for

ASKED = parse_time("2026-09-02 12:00")
CTX = ToolContext(engine=create_engine("sqlite://"), asked_at=ASKED)


def run(
    script: Any, config: AgentConfig | None = None, events: list[AgentEvent] | None = None
) -> tuple[Any, ScriptedRunner]:
    runner = ScriptedRunner(script)
    result = investigate(
        "Why did traffic drop at S-TUN-001?",
        ASKED,
        runner=runner,
        ctx=CTX,
        config=config,
        reference=REFERENCE,
        tool_executor=fake_tools,
        on_event=events.append if events is not None else None,
    )
    return result, runner


def calls(*tools: str) -> list[ToolCall]:
    return [ToolCall(name=t, args=dict(WINDOW)) for t in tools]


FULL_CHECK = calls("get_alarms", "get_maintenance", "get_changes")
CHECKS = [FULL_CHECK, calls("get_external_events")]


# --- the happy path and its events -------------------------------------------------------------


def test_run_produces_a_cited_report_and_ordered_events() -> None:
    events: list[AgentEvent] = []
    script = script_for(
        [*CHECKS, "Link alarm explains it; calendar clear."],
    )
    result, runner = run(script, events=events)

    types = [e.type for e in events]
    assert types[:2] == ["run_started", "llm_call"] and types[-1] == "run_finished"
    assert types.index("scope") < types.index("tool_call") < types.index("report")
    assert types.count("report") == 1 and types.index("report") > types.index("tool_result")
    assert [c.ref for c in result.calls][:2] == ["T1", "T2"]  # orient: anomalies, topology
    assert result.calls[0].node == "orient" and result.calls[0].tool == "get_anomalies"
    assert result.calls[1].tool == "get_topology"
    assert result.status == "finished" and result.report.confidence == "high"
    assert result.issues == []
    assert "## Sources" in result.markdown and "ALM-000001" in result.markdown
    # intake, 3 investigate turns, conclude
    assert [c.purpose for c in runner.calls] == [
        "intake",
        "investigate turn 1",
        "investigate turn 2",
        "investigate turn 3",
        "conclude",
    ]
    assert result.usage.llm_calls == 5 and result.usage.tool_calls == 6
    assert result.models_used == ["scripted:scripted"] and not result.fell_back


def test_stream_yields_the_same_events() -> None:
    runner = ScriptedRunner(script_for([*CHECKS, "done"]))
    events = list(
        stream("q", ASKED, runner=runner, ctx=CTX, reference=REFERENCE, tool_executor=fake_tools)
    )
    assert events[0].type == "run_started" and events[-1].type == "run_finished"
    assert events[-1].data["report"]["classification"] == "incident"


def test_each_model_call_is_built_from_the_case_file_alone() -> None:
    script = script_for([*CHECKS, "ok"])
    _, runner = run(script)
    for call in runner.calls:
        assert [m.type for m in call.messages] == ["system", "human"]
    assert "T3 get_alarms" in runner.calls[2].messages[1].text  # earlier calls are in the log
    assert runner.calls[1].tools and not runner.calls[1].schema
    assert runner.calls[0].schema and not runner.calls[0].tools


# --- caps and the gate -------------------------------------------------------------------------


def test_iteration_cap_ends_the_loop() -> None:
    keep_going = [calls("get_alarms"), calls("get_maintenance"), calls("get_changes")]
    result, runner = run(script_for(keep_going * 5), AgentConfig(max_iterations=3))
    turns = [c for c in runner.calls if c.purpose.startswith("investigate")]
    assert len(turns) == 3 and runner.calls[-1].purpose == "conclude"
    assert result.status == "finished"


def test_tool_call_cap_and_per_turn_limit() -> None:
    wide = calls(
        "get_alarms", "get_maintenance", "get_changes", "get_external_events", "get_topology"
    )
    result, runner = run(
        script_for([wide, wide, wide, wide]),
        AgentConfig(max_tool_calls=4, max_calls_per_iteration=3),
    )
    investigate_calls = [c for c in result.calls if c.node == "investigate"]
    assert len(investigate_calls) == 4
    conclude = runner.calls[-1].prompt
    assert "CASE FILE" in conclude
    turns = [c for c in runner.calls if c.purpose.startswith("investigate")]
    assert len(turns) == 2  # 3 calls, then 1 left, then the budget is gone
    assert "not run" in turns[1].prompt  # the model is told some of its calls were dropped


def test_gate_nudges_once_then_lets_the_model_conclude() -> None:
    events: list[AgentEvent] = []
    script = script_for(
        [
            calls("get_alarms"),
            "I am done.",  # stops with the calendar, changes and events unchecked
            "Still done.",  # stops again: the gate must not fire a second time
        ]
    )
    result, runner = run(script, events=events)
    gates = [e for e in events if e.type == "gate"]
    assert len(gates) == 1
    assert set(gates[0].data["missing"]) == {
        "the maintenance calendar",
        "the change log",
        "external events",
    }
    assert [c.purpose for c in runner.calls].count("investigate turn 3") == 1
    assert "[gate]" in runner.calls[3].prompt
    # The report is lowered because the checks were never made.
    assert result.report.confidence == "medium"
    assert any("not checked" in i for i in result.issues)


def test_gate_stays_quiet_when_the_checks_were_made() -> None:
    events: list[AgentEvent] = []
    run(script_for([*CHECKS, "done"]), events=events)
    assert not [e for e in events if e.type == "gate"]


def test_gate_can_be_turned_off() -> None:
    events: list[AgentEvent] = []
    result, runner = run(
        script_for([calls("get_alarms"), "done"]),
        AgentConfig(completeness_gate=False),
        events=events,
    )
    assert not [e for e in events if e.type == "gate"]
    assert [c.purpose for c in runner.calls].count("investigate turn 2") == 1
    assert result.status == "finished"


def test_duplicate_calls_are_not_run_twice_and_unknown_tools_report_an_error() -> None:
    script = script_for(
        [
            [ToolCall(name="get_alarms", args=WINDOW), ToolCall(name="get_alarms", args=WINDOW)],
            [ToolCall(name="restart_router", args={})],
            "done",
        ]
    )
    result, runner = run(script, AgentConfig(completeness_gate=False))
    dup = result.calls[3]
    assert dup.duplicate_of == "T3" and "not run again" in dup.headline
    assert result.usage.tool_calls == 4  # T1, T2, T3 and the unknown tool; the duplicate is free
    assert result.calls[4].error and "restart_router" in result.calls[4].error
    assert "Unknown tool" in runner.calls[3].prompt  # the model sees the error next turn


# --- verification ------------------------------------------------------------------------------


def test_fabricated_ref_is_repaired_with_one_extra_call() -> None:
    bad = make_report(findings=[Finding(claim="Made up", basis="observed", refs=["ALM-999999"])])
    good = make_report()
    result, runner = run(script_for([*CHECKS, "done"], [bad, good]))
    assert [c.purpose for c in runner.calls][-2:] == ["conclude", "repair 1"]
    assert "ALM-999999" in runner.calls[-1].prompt  # the problem is spelled out
    assert result.report.findings[0].claim == "Critical LOS on the link"
    assert any(i.startswith("[repaired]") for i in result.issues)
    assert not any("unresolved" in i for i in result.issues)


def test_unrepairable_report_gets_its_invalid_refs_stripped() -> None:
    bad = make_report(
        findings=[
            Finding(claim="Made up", basis="observed", refs=["ALM-999999"]),
            Finding(claim="Real", basis="observed", refs=["ALM-000001", "XYZ-1"]),
        ],
        root_cause_node_id="S-NOPE-999",
        impact_start="2030-01-01 00:00",
    )
    result, runner = run(script_for([*CHECKS, "done"], [bad, bad]))
    assert runner.calls[-1].purpose == "repair 1" and len(runner.calls) == 6
    r = result.report
    assert [f.claim for f in r.findings] == ["Real"] and r.findings[0].refs == ["ALM-000001"]
    assert r.root_cause_node_id is None and r.impact_start is None and r.confidence == "low"
    assert any("unresolved" in i for i in result.issues)
    assert "Verification notes" in result.markdown


def test_repairs_can_be_disabled() -> None:
    bad = make_report(findings=[Finding(claim="x", basis="inferred", refs=["NOPE-1"])])
    result, runner = run(
        script_for([*CHECKS, "done"], [bad]),
        AgentConfig(max_repairs=0),
    )
    assert "repair 1" not in [c.purpose for c in runner.calls]
    assert result.report.findings == []


def test_check_report_problems() -> None:
    evidence = {
        "ALM-000001": EvidenceRef(ref="ALM-000001", kind="alarm", summary="x"),
        "MW-0001": EvidenceRef(ref="MW-0001", kind="maintenance", summary="x"),
        "T3": EvidenceRef(ref="T3", kind="call", summary="x"),
    }
    ok = check_report(make_report(), evidence, REFERENCE, ASKED)
    assert ok.problems == []
    spelled = make_report(
        findings=[Finding(claim="c", basis="observed", refs=["[alm-000001]", " t3 "])]
    )
    checked = check_report(spelled, evidence, REFERENCE, ASKED)
    assert checked.report.findings[0].refs == ["ALM-000001", "T3"]
    bad = make_report(
        classification="planned_maintenance",
        impact_end="2026-09-02 13:00",
        timeline=[],
        findings=[Finding(claim="c", basis="observed", refs=[])],
        root_cause_time="yesterday",
    )
    text = " ".join(check_report(bad, evidence, REFERENCE, ASKED).problems)
    for fragment in ("does not match", "after now", "not a time", "no valid reference"):
        assert fragment in text


def test_strip_invalid_fixes_contradictory_classification() -> None:
    bad = make_report(classification="planned_maintenance")
    stripped, notes = strip_invalid(bad, REFERENCE, ASKED)
    assert stripped.classification == "inconclusive" and stripped.confidence == "low" and notes


@pytest.mark.parametrize(
    ("report_kwargs", "missing", "expected"),
    [
        ({}, [], "high"),
        ({}, ["external events"], "medium"),
        ({"classification": "inconclusive", "root_cause_category": "unknown"}, [], "low"),
        ({"confidence": "medium"}, ["external events"], "medium"),
    ],
)
def test_confidence_cap(report_kwargs: dict[str, Any], missing: list[str], expected: str) -> None:
    evidence = {
        "ALM-000001": EvidenceRef(ref="ALM-000001", kind="alarm", summary="x"),
        "MW-0001": EvidenceRef(ref="MW-0001", kind="maintenance", summary="x"),
    }
    capped, _ = cap_confidence(make_report(**report_kwargs), evidence, {}, missing)
    assert capped.confidence == expected


def test_one_kind_of_evidence_is_not_enough_for_high_confidence() -> None:
    evidence = {"ALM-000001": EvidenceRef(ref="ALM-000001", kind="alarm", summary="x")}
    report = make_report(findings=[Finding(claim="c", basis="observed", refs=["ALM-000001"])])
    capped, notes = cap_confidence(report, evidence, {}, [])
    assert capped.confidence == "medium" and "two kinds" in notes[0]


def test_planned_maintenance_needs_a_maintenance_record_for_high_confidence() -> None:
    report = make_report(
        classification="planned_maintenance", root_cause_category="planned_maintenance"
    )
    no_record = {"ALM-000001": EvidenceRef(ref="ALM-000001", kind="alarm", summary="x")}
    assert cap_confidence(report, no_record, {}, [])[0].confidence == "medium"
    with_record = no_record | {
        "MW-0001": EvidenceRef(ref="MW-0001", kind="maintenance", summary="x")
    }
    assert cap_confidence(report, with_record, {}, [])[0].confidence == "high"


# --- failures ----------------------------------------------------------------------------------


def test_intake_failure_falls_back_to_the_default_window() -> None:
    def script(call: RecordedCall) -> Any:
        if call.purpose == "intake":
            return RuntimeError("provider down")
        return script_for([*CHECKS, "done"])(call)

    result, _ = run(script)
    assert result.scope is not None and result.scope.source == "default"
    assert (result.scope.window_end - result.scope.window_start).total_seconds() == 24 * 3600
    assert any("intake failed" in i for i in result.issues)


def test_conclude_failure_yields_an_honest_fallback_report() -> None:
    def script(call: RecordedCall) -> Any:
        if call.purpose == "conclude" or call.purpose.startswith("repair"):
            return RuntimeError("quota exhausted")
        return script_for([*CHECKS, "done"])(call)

    result, _ = run(script)
    assert result.status == "error" and result.error
    assert result.report.classification == "inconclusive" and result.report.confidence == "low"
    assert result.report.findings and all(f.refs for f in result.report.findings)
    assert "quota exhausted" in result.markdown


def test_investigate_failure_goes_straight_to_conclude() -> None:
    def script(call: RecordedCall) -> Any:
        if call.purpose.startswith("investigate"):
            return RuntimeError("timeout")
        return script_for([])(call)

    result, runner = run(script, AgentConfig(max_repairs=0))
    assert [c.purpose for c in runner.calls] == ["intake", "investigate turn 1", "conclude"]
    assert any("investigation stopped early" in i for i in result.issues)


# --- intake scope ------------------------------------------------------------------------------


def _deps() -> Deps:
    return Deps(runner=ScriptedRunner([]), ctx=CTX, config=AgentConfig(), reference=REFERENCE)


def _intake(**over: Any) -> IntakeOutput:
    base: dict[str, Any] = {
        "symptom": "drop",
        "window_start": "2026-09-02 08:00",
        "window_end": "2026-09-02 11:00",
        "region_ids": ["tun"],
        "node_ids": ["s-tun-001", "S-NOPE-1", "SFX"],
        "nationwide": False,
        "ongoing": False,
    }
    return IntakeOutput.model_validate(base | over)


def test_scope_ids_are_canonicalised_and_unknown_ones_kept_aside() -> None:
    scope = build_scope(_intake(), ASKED, _deps())
    assert scope.region_ids == ["TUN", "SFX"] and scope.node_ids == ["S-TUN-001"]
    assert scope.unknown_ids == ["S-NOPE-1"] and scope.source == "model"


def test_scope_window_is_clamped_and_defaulted() -> None:
    late = build_scope(
        _intake(window_start="2026-09-02 09:00", window_end="2026-09-03 09:00"), ASKED, _deps()
    )
    assert late.window_end == ASKED
    ongoing = build_scope(_intake(ongoing=True), ASKED, _deps())
    assert ongoing.window_end == ASKED
    for bad in (
        {"window_start": "banana", "window_end": None},
        {"window_start": "2026-09-05 00:00"},
    ):
        s = build_scope(_intake(**bad), ASKED, _deps())
        assert s.source == "default" and s.window_end == ASKED
    only_start = build_scope(_intake(window_end=None), ASKED, _deps())
    assert only_start.window_end == ASKED and only_start.source == "model"


def test_id_pattern_and_reference_lookup() -> None:
    regions = {"TUN", "SFX"}
    assert id_pattern("S-TUN-012", regions) == "S-<REGION>-nnn"
    assert id_pattern("LNK-TUN-02-C", regions) == "LNK-<REGION>-nn-<letter>"
    assert REFERENCE.canonical(" `s-tun-001` ") == "S-TUN-001" and REFERENCE.canonical("X") is None


# --- the case file -----------------------------------------------------------------------------


def _long_state(n_calls: int = 14, n_notes: int = 8) -> AgentState:
    scope = Scope(
        symptom="traffic drop",
        window_start=parse_time("2026-09-02 08:00"),
        window_end=ASKED,
        region_ids=["TUN"],
        node_ids=["S-TUN-001"],
    )
    state = AgentState(run_id="RUN-x", question="Why?" * 20, asked_at=ASKED, scope=scope)
    for n in range(1, n_calls + 1):
        state.calls.append(
            CallRecord(
                ref=f"T{n}",
                node="investigate",
                iteration=n // 3,
                tool="get_alarms",
                args={
                    "start": "2026-09-02 08:00",
                    "end": "2026-09-02 12:00",
                    "node_ids": ["S-TUN-001"],
                },
                headline=f"{n} alarms " + "word " * 60,
                body=f"BODY-{n} " + "x" * 1900,
            )
        )
    for n in range(1, n_notes + 1):
        state.notes.append(Note(iteration=n, text=f"NOTE-{n} " + "thought " * 200))
    state.tool_calls_used = n_calls
    state.iteration = n_notes
    return state


def test_case_file_stays_within_the_budget_on_a_long_run() -> None:
    config = AgentConfig()
    text = render_case_file(_long_state(), config)
    assert len(text) <= config.casefile_chars
    est_tokens = len(text) / 3.5  # the runner's pessimistic estimate
    assert est_tokens < 3_300  # leaves room for the system prompt and tool schemas under 5.5k
    assert all(f"T{n} get_alarms" in text for n in range(1, 15))  # every call stays in the log
    assert "BODY-14" in text and "BODY-1 " not in text  # only the newest results are in full
    assert "NOTE-8" in text and "older note(s) not shown" in text


def test_case_file_small_run_shows_everything() -> None:
    state = _long_state(n_calls=2, n_notes=1)
    text = render_case_file(state, AgentConfig())
    assert "BODY-1" in text and "BODY-2" in text and "NOTE-1" in text
    assert "turn 1 of 6" in text or "turn 2 of 6" in text


def test_registry_lists_non_call_refs_by_importance_within_its_budget() -> None:
    state = _long_state(2, 0)
    state.evidence = {
        "T1": EvidenceRef(ref="T1", kind="call", summary="call"),
        "S-TUN-001": EvidenceRef(ref="S-TUN-001", kind="node", summary="a site"),
        "ALM-000001": EvidenceRef(ref="ALM-000001", kind="alarm", summary="LOS"),
        **{
            f"CHG-{n}": EvidenceRef(ref=f"CHG-{n}", kind="change", summary="c" * 120)
            for n in range(80)
        },
    }
    text = render_registry(state, AgentConfig(registry_chars=1_000))
    assert len(text) < 1_300 and text.splitlines()[0].startswith("ALM-000001")
    assert "T1" not in text.splitlines()[0] and "more ids appear" in text


def test_missing_checks_considers_window_and_region() -> None:
    state = _long_state(0, 0)
    assert len(missing_checks(state)) == 3

    def add(tool: str, **args: Any) -> None:
        state.calls.append(
            CallRecord(
                ref=f"T{len(state.calls) + 1}", node="investigate", iteration=1, tool=tool,
                args=args, headline="h", body="b",
            )
        )  # fmt: skip

    add("get_maintenance", **WINDOW)
    add("get_changes", start="2026-08-01 00:00", end="2026-08-02 00:00")  # outside the window
    add("get_external_events", region_id="SFX", **WINDOW)  # a different region
    assert missing_checks(state) == ["the change log", "external events"]
    add("get_changes", **WINDOW)
    add("get_external_events", region_id="TUN", **WINDOW)
    assert missing_checks(state) == []


def test_markdown_separates_observed_from_inferred() -> None:
    report = make_report(
        findings=[
            Finding(claim="Alarm seen", basis="observed", refs=["ALM-000001"]),
            Finding(claim="Probably the fiber", basis="inferred", refs=["ALM-000001"]),
        ]
    )
    md = render_markdown(
        report, {"ALM-000001": EvidenceRef(ref="ALM-000001", kind="alarm", summary="LOS")}
    )
    assert md.index("## Evidence") < md.index("Alarm seen") < md.index("## Inferences")
    assert md.index("## Inferences") < md.index("Probably the fiber")
    assert "`ALM-000001`: LOS" in md
    assert "ongoing" in md  # impact_end is null
    assert fallback_report("x", []).classification == "inconclusive"


def test_datetimes_in_events_are_json_safe() -> None:
    events = list(
        stream(
            "q", datetime(2026, 9, 2, 11, 0, tzinfo=UTC),
            runner=ScriptedRunner(script_for([*CHECKS, "done"])),
            ctx=CTX, reference=REFERENCE, tool_executor=fake_tools,
        )
    )  # fmt: skip
    for event in events:
        event.model_dump_json()


def test_no_impact_without_a_positive_explanation_is_low_confidence() -> None:
    report = make_report(
        classification="no_impact",
        root_cause_category="no_impact",
        findings=[Finding(claim="KPIs look normal", basis="observed", refs=["T3"])],
        hypotheses=[],
    )
    only_calls = {"T3": EvidenceRef(ref="T3", kind="call", summary="x")}
    capped, notes = cap_confidence(report, only_calls, {"T3": "query_kpis"}, [])
    assert capped.confidence == "low" and "symptom not found" in notes[0]
    with_alarm = only_calls | {
        "ALM-000001": EvidenceRef(ref="ALM-000001", kind="alarm", summary="x")
    }
    explained = report.model_copy(
        update={"findings": [Finding(claim="Noise", basis="observed", refs=["ALM-000001", "T3"])]}
    )
    assert cap_confidence(explained, with_alarm, {"T3": "query_kpis"}, [])[0].confidence == "high"


def test_the_conclude_message_lists_checks_that_were_not_made() -> None:
    from incident_agent.agent.casefile import conclude_message

    state = _long_state(2, 0)
    assert "NOT CHECKED (no tool call made): the maintenance calendar" in conclude_message(
        state, AgentConfig()
    )
    for tool in ("get_maintenance", "get_changes", "get_external_events"):
        state.calls.append(
            CallRecord(
                ref=f"T{len(state.calls) + 1}", node="investigate", iteration=1, tool=tool,
                args=dict(WINDOW), headline="h", body="b",
            )
        )  # fmt: skip
    assert "NOT CHECKED" not in conclude_message(state, AgentConfig())
