"""Report reliability: output budget, retry, salvage of a cut-off answer, limits, cheap checks."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from incident_agent.agent import AgentConfig, investigate
from incident_agent.agent.prompts import CONCISE_SUFFIX
from incident_agent.agent.report import (
    MAX_ACTIONS,
    MAX_DISMISSED,
    MAX_FINDINGS,
    MAX_HYPOTHESES,
    MAX_TIMELINE,
    DismissedSignal,
    Finding,
    HypothesisEntry,
    Report,
    TimelineEntry,
    limit_report,
)
from incident_agent.agent.salvage import salvage_report
from incident_agent.agent.state import CallRecord
from incident_agent.agent.tools.timeutil import parse_time
from incident_agent.agent.types import EvidenceRef, ToolContext
from incident_agent.agent.verify import check_faithfulness
from incident_agent.config import Settings
from incident_agent.evals.types import CaseArtifact
from incident_agent.llm.runner import ChainEntry, LLMRunner
from incident_agent.llm.testing import FakeChatModel, RecordedCall, ScriptedRunner, ai
from incident_agent.llm.types import MalformedOutput, ToolCall
from tests.agent_support import REFERENCE, WINDOW, fake_tools, make_report, script_for

ASKED = parse_time("2026-09-02 12:00")
CTX = ToolContext(engine=create_engine("sqlite://"), asked_at=ASKED)
CHECKS = [
    [ToolCall(name=t, args=dict(WINDOW)) for t in ("get_alarms", "get_maintenance", "get_changes")],
    [ToolCall(name="get_external_events", args=dict(WINDOW))],
    "done",
]
REPO_ROOT = Path(__file__).resolve().parents[2]


def run(script: Any, config: AgentConfig | None = None, reference: Any = REFERENCE) -> Any:
    runner = ScriptedRunner(script)
    result = investigate(
        "Why did traffic drop at S-TUN-001?",
        ASKED,
        runner=runner,
        ctx=CTX,
        config=config,
        reference=reference,
        tool_executor=fake_tools,
    )
    return result, runner


def cut_off_json(keep: str = '"findings": [{"claim": "Cri') -> str:
    """The report as JSON, ended in the middle of the findings the way a token limit would."""
    full = json.dumps(make_report().model_dump())
    return full[: full.index(keep) + len(keep)]


def conclude_script(first: Any, second: Any) -> Any:
    """Investigation as usual; the first conclude call answers `first`, the retry `second`."""
    base = script_for(CHECKS)

    def script(call: RecordedCall) -> Any:
        if call.purpose == "conclude":
            return first
        if call.purpose.startswith("conclude retry"):
            return second
        return base(call)

    return script


# --- the report call gets a larger budget and one retry ----------------------------------------


def test_conclude_and_repair_ask_for_a_larger_output_budget() -> None:
    bad = make_report(findings=[Finding(claim="Made up", basis="observed", refs=["ALM-999999"])])
    _, runner = run(script_for(CHECKS, [bad, make_report()]))
    by_purpose = {c.purpose: c.max_output_tokens for c in runner.calls}
    assert by_purpose["conclude"] == by_purpose["repair 1"] == 3072
    assert by_purpose["investigate turn 1"] is None and by_purpose["intake"] is None
    _, small = run(script_for(CHECKS), AgentConfig(conclude_max_output_tokens=3000))
    assert small.calls[-1].max_output_tokens == 3000


def test_a_cut_off_report_is_asked_again_more_concisely() -> None:
    cut = MalformedOutput("structured output invalid (finish_reason=MAX_TOKENS)", cut_off_json())
    result, runner = run(conclude_script(cut, make_report()))
    purposes = [c.purpose for c in runner.calls]
    assert purposes[-2:] == ["conclude", "conclude retry 1"]
    assert CONCISE_SUFFIX.strip() in runner.calls[-1].prompt
    assert CONCISE_SUFFIX.strip() not in runner.calls[-2].prompt
    assert runner.calls[-1].max_output_tokens == 3072
    assert result.status == "finished" and result.error is None
    assert result.report.confidence == "high" and "Partial" not in result.markdown
    failed = [s for s in result.steps if s.error]
    assert len(failed) == 1 and failed[0].raw_output == cut_off_json()


def test_a_rate_limit_is_not_retried() -> None:
    result, runner = run(conclude_script(RuntimeError("429 quota exhausted"), make_report()))
    assert not [c for c in runner.calls if c.purpose.startswith("conclude retry")]
    assert result.status == "error" and result.report.classification == "inconclusive"


def test_retries_can_be_turned_off() -> None:
    cut = MalformedOutput("structured output invalid", cut_off_json())
    result, runner = run(conclude_script(cut, make_report()), AgentConfig(conclude_retries=0))
    assert not [c for c in runner.calls if c.purpose.startswith("conclude retry")]
    assert any("Partial" in line or "partial" in line for line in result.issues)


# --- salvage ----------------------------------------------------------------------------------


def test_two_cut_off_answers_give_a_partial_low_confidence_report() -> None:
    cut = MalformedOutput("structured output invalid", cut_off_json())
    result, runner = run(conclude_script(cut, cut))
    assert [c.purpose for c in runner.calls][-2:] == ["conclude", "conclude retry 1"]
    r = result.report
    assert r.classification == "incident" and r.root_cause_category == "transport_failure"
    assert r.root_cause_node_id == "LNK-TUN-01-A" and "lost light" in r.root_cause_summary
    assert r.affected_node_ids == ["S-TUN-001", "S-TUN-002"]
    assert r.impact_start == "2026-09-02 09:00"
    assert r.confidence == "low"  # the original said "high"
    assert result.status == "finished" and result.error is None
    partial = [i for i in result.issues if i.startswith("partial report:")]
    assert len(partial) == 1
    assert "Partial report" in result.markdown.splitlines()[2]
    assert r.findings and all(f.refs for f in r.findings)  # the raw call results are kept
    assert "repair 1" not in [c.purpose for c in runner.calls]  # no repair of a partial report


def test_a_real_runner_hands_the_cut_off_text_to_the_salvage(tmp_path: Path) -> None:
    """The text survives the runner (attempts, scrubbing, fallback) on its way to the node."""
    chat = FakeChatModel(script=[ai(cut_off_json()), ai(cut_off_json())])
    real = LLMRunner(
        chain=[ChainEntry("gemini:fake", chat)],
        settings=Settings(_env_file=None, llm_cache_dir=tmp_path),
        cache_mode="off",
        min_interval_seconds=0,
    )
    base = script_for(CHECKS)

    def script(call: RecordedCall) -> Any:
        if call.purpose.startswith("conclude"):
            return real.invoke(call.messages, schema=call.schema, purpose=call.purpose)
        return base(call)

    result, _ = run(script)
    assert len(chat.seen) == 2  # the first answer and the retry
    assert result.report.root_cause_node_id == "LNK-TUN-01-A" and result.report.confidence == "low"
    assert any(i.startswith("partial report:") for i in result.issues)


def test_nothing_recoverable_falls_back_to_the_inconclusive_report() -> None:
    nothing = MalformedOutput("structured output invalid", '{"title": "Fiber cut on LNK')
    result, _ = run(conclude_script(nothing, nothing))
    assert result.status == "error" and result.error and result.error.startswith("conclude failed")
    assert result.report.title == "Investigation incomplete"
    assert not any(i.startswith("partial report:") for i in result.issues)
    no_text = MalformedOutput("empty answer")
    result, _ = run(conclude_script(no_text, no_text))
    assert result.report.title == "Investigation incomplete"


def test_salvage_reads_the_fields_before_the_break() -> None:
    raw = cut_off_json('"impact_summary": "Two sites down')
    report = salvage_report(raw, [])
    assert report is not None
    assert report.root_cause_node_id == "LNK-TUN-01-A" and report.confidence == "low"
    assert report.impact_summary.startswith("Not recovered")  # that string was cut
    escaped = '{"root_cause_category": "capacity", "root_cause_summary": "Say \\"hi\\"", "x'
    got = salvage_report(escaped, [])
    assert got is not None and got.root_cause_summary == 'Say "hi"'
    assert got.classification == "incident" and got.root_cause_node_id is None


def test_salvage_derives_the_category_from_a_classification_without_one() -> None:
    raw = '{"classification": "planned_maintenance", "root_cause_node_id": null, "root_cause_su'
    report = salvage_report(raw, [])
    assert report is not None and report.root_cause_category == "planned_maintenance"
    assert salvage_report('{"classification": "incident"', []) is None
    assert salvage_report('{"root_cause_category": "aliens"', []) is None


# --- limits ------------------------------------------------------------------------------------


def test_the_report_is_cut_to_its_section_limits_with_a_note() -> None:
    many = make_report(
        timeline=[
            TimelineEntry(time="2026-09-02 09:00", event=f"e{n}", refs=["T1"]) for n in range(12)
        ],
        findings=[Finding(claim=f"c{n}", basis="observed", refs=["T1"]) for n in range(9)],
        hypotheses=[
            HypothesisEntry(
                category="capacity", node_id=None, verdict="rejected", reason="r", refs=["T1"]
            )
            for _ in range(6)
        ],
        dismissed_signals=[DismissedSignal(ref="T1", reason="x") for _ in range(8)],
        recommended_actions=[f"a{n}" for n in range(7)],
    )
    cut, notes = limit_report(many)
    assert len(cut.timeline) == MAX_TIMELINE and len(cut.findings) == MAX_FINDINGS
    assert len(cut.hypotheses) == MAX_HYPOTHESES and len(cut.dismissed_signals) == MAX_DISMISSED
    assert len(cut.recommended_actions) == MAX_ACTIONS and len(notes) == 5
    assert limit_report(cut) == (cut, [])
    result, _ = run(script_for(CHECKS, many))
    assert len(result.report.findings) == MAX_FINDINGS
    assert any("cut to 6 findings" in i for i in result.issues)


def test_the_schema_tells_the_model_the_limits() -> None:
    props = Report.model_json_schema()["properties"]
    assert "At most 8" in props["timeline"]["description"]
    assert "At most 6" in props["findings"]["description"]
    assert "30 words" in props["confidence_reason"]["description"]


# --- cheap checks of what the report claims ------------------------------------------------------

TREE = replace(
    REFERENCE,
    node_ids=REFERENCE.node_ids | {"CORE-UPF-01"},
    parent_of={
        "S-TUN-001": "LNK-TUN-01-A",
        "S-TUN-002": "LNK-TUN-01-A",
        "LNK-TUN-01-A": "AGG-TUN-01",
        "AGG-TUN-01": "CORE-UPF-01",
        "C-TUN-001-1": "S-TUN-001",
    },
)
EVIDENCE = {
    "T3": EvidenceRef(ref="T3", kind="call", summary="get_changes"),
    "T4": EvidenceRef(ref="T4", kind="call", summary="get_topology"),
    "T5": EvidenceRef(ref="T5", kind="call", summary="query_kpis"),
    "ALM-000001": EvidenceRef(
        ref="ALM-000001", kind="alarm", summary="critical LINK_LOS on LNK-TUN-01-A, raised 09:00"
    ),
    "ALM-000009": EvidenceRef(
        ref="ALM-000009", kind="alarm", summary="major CPU_HIGH on AGG-TUN-01, raised 08:55"
    ),
    "CHG-1": EvidenceRef(ref="CHG-1", kind="change", summary="upgrade on S-TUN-001 at 08:00"),
    "AGG-TUN-01": EvidenceRef(ref="AGG-TUN-01", kind="node", summary="agg router"),
}


def call(ref: str, tool: str, error: str | None = None, **args: Any) -> CallRecord:
    return CallRecord(
        ref=ref, node="investigate", iteration=1, tool=tool, args=args, headline="h", body="b",
        error=error,
    )  # fmt: skip


CALLS = [
    call("T3", "get_changes", node_ids=["S-TUN-001"], **WINDOW),
    call("T4", "get_topology", node_id="AGG-TUN-01"),
    call("T5", "query_kpis", entity_type="site", entity_ids=["S-TUN-001"], **WINDOW),
]


def findings(*pairs: tuple[str, list[str]]) -> list[Finding]:
    return [Finding(claim=c, basis="observed", refs=r) for c, r in pairs]


def test_an_absence_claim_must_cite_a_call_of_the_tool_that_looks() -> None:
    report = make_report(
        findings=findings(
            ("No changes on the sites during the incident", ["CHG-1"]),
            ("There were no config changes", ["T3"]),
            ("No maintenance window covers the link", ["T3"]),
            ("No external events and no alarms on the siblings", ["T5"]),
            ("Critical alarm on the link", ["ALM-000001"]),
        )
    )
    _, notes = check_faithfulness(report, EVIDENCE, CALLS, REFERENCE)
    assert len(notes) == 4
    assert "Finding 1 claims no changes but cites no get_changes call" in notes[0]
    assert "Finding 3 claims no maintenance" in notes[1]
    assert "no external events" in notes[2] and "no alarms" in notes[3]


def test_ordinary_sentences_are_not_taken_for_absence_claims() -> None:
    report = make_report(
        findings=findings(
            ("No change in availability on the sibling sites", ["T5"]),
            ("No sibling shows a deviation, and alarms are active on the link", ["ALM-000001"]),
            ("The upgrade was not followed by a rollback", ["T3"]),
        )
    )
    assert check_faithfulness(report, EVIDENCE, CALLS, REFERENCE)[1] == []


def test_a_failed_call_does_not_back_an_absence_claim() -> None:
    report = make_report(findings=findings(("No changes were logged", ["T3"])))
    failed = [call("T3", "get_changes", error="Invalid arguments")]
    assert len(check_faithfulness(report, EVIDENCE, failed, REFERENCE)[1]) == 1
    assert check_faithfulness(report, EVIDENCE, CALLS, REFERENCE)[1] == []


def test_a_parent_named_without_evidence_on_it_is_capped_at_medium() -> None:
    report = make_report(
        root_cause_node_id="AGG-TUN-01",
        affected_node_ids=["S-TUN-001", "S-TUN-002"],
        findings=findings(("Both sites degraded together", ["T5"]), ("Shared router", ["T4"])),
        hypotheses=[],
    )
    fixed, notes = check_faithfulness(report, EVIDENCE, CALLS, TREE)
    assert fixed.confidence == "medium"
    assert len(notes) == 1 and "AGG-TUN-01 is a parent of every affected node" in notes[0]
    low = report.model_copy(update={"confidence": "low"})
    assert check_faithfulness(low, EVIDENCE, CALLS, TREE)[0].confidence == "low"


def test_evidence_on_the_parent_clears_it() -> None:
    base = {"root_cause_node_id": "AGG-TUN-01", "affected_node_ids": ["S-TUN-001", "S-TUN-002"]}
    alarm = make_report(**base, findings=findings(("CPU alarm on the router", ["ALM-000009"])))
    assert check_faithfulness(alarm, EVIDENCE, CALLS, TREE) == (alarm, [])
    queried = [*CALLS, call("T6", "get_alarms", node_ids=["AGG-TUN-01"], **WINDOW)]
    ev = EVIDENCE | {"T6": EvidenceRef(ref="T6", kind="call", summary="get_alarms")}
    by_call = make_report(
        **base, findings=findings(("Router alarms checked", ["T6"])), hypotheses=[]
    )
    assert check_faithfulness(by_call, ev, queried, TREE) == (by_call, [])


def test_the_check_only_applies_to_a_parent_of_every_affected_node() -> None:
    link = make_report(findings=findings(("Sites degraded", ["T5"])), hypotheses=[], timeline=[])
    # the link is the parent of both sites: no evidence on it is cited, so it is flagged
    assert len(check_faithfulness(link, EVIDENCE, CALLS, TREE)[1]) == 1
    # a site that is not below the link: the premise (parent of all) fails
    mixed = link.model_copy(update={"affected_node_ids": ["S-TUN-001", "S-SFX-001"]})
    assert check_faithfulness(mixed, EVIDENCE, CALLS, TREE)[1] == []
    # the node itself is affected (not a parent) and a topology that is not loaded: no check
    same = link.model_copy(update={"affected_node_ids": ["LNK-TUN-01-A"]})
    assert check_faithfulness(same, EVIDENCE, CALLS, TREE)[1] == []
    assert check_faithfulness(link, EVIDENCE, CALLS, REFERENCE)[1] == []
    cells = link.model_copy(update={"affected_node_ids": ["C-TUN-001-1"]})
    assert len(check_faithfulness(cells, EVIDENCE, CALLS, TREE)[1]) == 1


def test_a_topology_lookup_is_not_evidence_about_the_parent() -> None:
    report = make_report(
        root_cause_node_id="AGG-TUN-01",
        affected_node_ids=["S-TUN-001", "S-TUN-002"],
        findings=findings(("Router above both sites", ["T4", "AGG-TUN-01"])),
        hypotheses=[],
    )
    assert len(check_faithfulness(report, EVIDENCE, CALLS, TREE)[1]) == 1


def test_the_checks_run_in_the_graph_and_land_in_the_issues() -> None:
    bad = make_report(
        root_cause_node_id="AGG-TUN-01",
        affected_node_ids=["S-TUN-001", "S-TUN-002"],
        findings=findings(("No changes on the router", ["ALM-000001"])),
        hypotheses=[],
    )
    result, _ = run(script_for(CHECKS, bad), reference=TREE)
    assert result.report.confidence == "medium"
    assert any("claims no changes" in i for i in result.issues)
    assert any("parent of every affected node" in i for i in result.issues)


# --- saved runs keep loading ---------------------------------------------------------------------


def test_every_saved_case_still_loads() -> None:
    cases = sorted((REPO_ROOT / "evals" / "runs").glob("*/cases/*.json"))
    if not cases:
        pytest.skip("no saved runs in this checkout")
    for path in cases:
        artifact = CaseArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        if artifact.result is not None:
            assert artifact.result.steps and artifact.result.report.title
            assert all(s.raw_output is None for s in artifact.result.steps)  # a newer field
