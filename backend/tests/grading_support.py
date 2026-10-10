"""Hand-made artifacts and a scripted judge for the grading tests."""

import re
from datetime import UTC, datetime
from typing import Any

from incident_agent.agent.report import Finding, HypothesisEntry, Report
from incident_agent.agent.state import CallRecord, RunResult, UsageTotals
from incident_agent.agent.types import EvidenceRef
from incident_agent.evals.grader import VerdictBatch
from incident_agent.evals.types import CaseArtifact, EvalCase, Truth
from incident_agent.llm.testing import RecordedCall

NOW = datetime(2026, 9, 22, 8, 38, tzinfo=UTC)

ALARMS_BODY = (
    "2 alarm(s) on S-TUN-012, 2026-09-21 15:00 to 2026-09-21 19:00: 2 critical.\n"
    "2026-09-21 16:50 ALM-000472 critical LINK_LOS LNK-TUN-02-C: cleared 2026-09-22 00:26\n"
    "  detail line one of the alarm\n"
    "  detail line two of the alarm\n"
    "2026-09-21 16:51 ALM-000474 critical SITE_DOWN S-TUN-012: cleared 2026-09-22 00:29"
)
CHANGES_BODY = (
    "No changes on S-TUN-012 and its parents between 2026-09-21 12:00 and 2026-09-21 19:00."
)

# Strings that must never reach a judge or a person grading.
TRUTH_NOTES = "TRUTH-NOTES-SENTINEL"
TRUTH_KIND = "kind-sentinel-xyz"


def make_call(ref: str, tool: str, body: str, **extra: Any) -> CallRecord:
    return CallRecord(
        ref=ref,
        node="investigate",
        iteration=1,
        tool=tool,
        args=extra.pop("args", {"start": "2026-09-21 15:00", "node_ids": ["S-TUN-012"]}),
        headline=body.splitlines()[0] if body else "",
        body=body,
        **extra,
    )


def make_report(findings: list[Finding] | None = None, **over: Any) -> Report:
    findings = (
        findings
        if findings is not None
        else [
            Finding(
                claim="Link LNK-TUN-02-C lost signal at 16:50.",
                basis="observed",
                refs=["T1", "ALM-000472"],
            ),
            Finding(claim="No configuration changes were made.", basis="observed", refs=["T2"]),
            Finding(claim="The site is on the failed link.", basis="inferred", refs=["S-TUN-012"]),
        ]
    )
    base: dict[str, Any] = {
        "title": "Fiber cut on LNK-TUN-02-C",
        "classification": "incident",
        "root_cause_category": "transport_failure",
        "root_cause_node_id": "LNK-TUN-02-C",
        "root_cause_summary": "A fiber link loss on LNK-TUN-02-C took down S-TUN-012.",
        "confidence": "high",
        "confidence_reason": "Alarms agree.",
        "impact_summary": "One site down.",
        "impact_start": "2026-09-21 16:50",
        "impact_end": None,
        "root_cause_time": "2026-09-21 16:50",
        "affected_node_ids": ["S-TUN-012"],
        "timeline": [],
        "findings": findings,
        "hypotheses": [
            HypothesisEntry(
                category="transport_failure",
                node_id="LNK-TUN-02-C",
                verdict="confirmed",
                reason="LOS alarm",
                refs=["T1", "ALM-000472"],
            ),
        ],
        "dismissed_signals": [],
        "recommended_actions": [],
    }
    base.update(over)
    return Report(**base)


def make_result(report: Report | None = None, **over: Any) -> RunResult:
    calls = over.pop(
        "calls",
        [
            make_call("T1", "get_alarms", ALARMS_BODY, row_refs=["ALM-000472", "ALM-000474"]),
            make_call("T2", "get_changes", CHANGES_BODY),
            make_call("T3", "get_alarms", "Identical to T1; not run again.", duplicate_of="T1"),
        ],
    )
    evidence = over.pop(
        "evidence",
        {
            "T1": EvidenceRef(ref="T1", kind="call", summary="T1 call get_alarms"),
            "T2": EvidenceRef(ref="T2", kind="call", summary="T2 call get_changes"),
            "ALM-000472": EvidenceRef(
                ref="ALM-000472", kind="alarm", summary="alarm critical LINK_LOS on LNK-TUN-02-C"
            ),
            "ALM-000474": EvidenceRef(
                ref="ALM-000474", kind="alarm", summary="alarm critical SITE_DOWN on S-TUN-012"
            ),
            "S-TUN-012": EvidenceRef(ref="S-TUN-012", kind="node", summary="node site, TUN"),
        },
    )
    return RunResult(
        run_id="RUN-1",
        question="Why did S-TUN-012 go down?",
        asked_at=NOW,
        status="finished",
        scope=None,
        report=report or make_report(),
        markdown="",
        usage=UsageTotals(),
        models_used=["scripted:scripted"],
        fell_back=False,
        issues=[],
        steps=[],
        calls=calls,
        evidence=evidence,
        **over,
    )


def make_truth(**over: Any) -> Truth:
    base: dict[str, Any] = {
        "kind": TRUTH_KIND,
        "is_incident": True,
        "root_cause_category": "transport_failure",
        "root_cause_node_id": "LNK-TUN-02-C",
        "start_at": NOW,
        "impact_start_at": NOW,
        "end_at": NOW,
        "affected_node_ids": ["S-TUN-012"],
        "affected_region_ids": ["TUN"],
        "severity": "high",
        "difficulty": "easy",
        "evidence": [],
        "expected_tools": ["get_alarms"],
        "confounders": [],
        "notes": TRUTH_NOTES,
    }
    base.update(over)
    return Truth(**base)


def make_artifact(
    case_id: str = "s42-SCN-001-q0",
    *,
    result: RunResult | None = None,
    truth: Truth | None = None,
    error: str | None = None,
) -> CaseArtifact:
    return CaseArtifact(
        case=EvalCase(
            case_id=case_id,
            seed=42,
            split="dev",
            scenario_id=case_id.split("-", 1)[1].rsplit("-", 1)[0],
            question_index=0,
            question="Why did S-TUN-012 go down?",
            asked_at=NOW,
        ),
        truth=truth or make_truth(),
        run_name="unit",
        variant="default",
        agent_model="gemini:test",
        result=result if result is not None or error else make_result(),
        error=error,
        created_at=NOW,
    )


def verdict_script(
    verdicts: dict[int, str] | str = "supported", reason: str = "Shown in the evidence."
) -> Any:
    """A judge script: answers every claim number found in the request (or the given ones)."""

    def script(call: RecordedCall) -> VerdictBatch:
        text = call.messages[-1].text
        numbers = [int(n) for n in re.findall(r"^\[(\d+)\] \(", text, flags=re.M)]
        out = []
        for n in numbers:
            v = verdicts if isinstance(verdicts, str) else verdicts.get(n)
            if v is not None:
                out.append({"item": n, "reason": reason, "verdict": v})
        return VerdictBatch.model_validate({"verdicts": out})

    return script
