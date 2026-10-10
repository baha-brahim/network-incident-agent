"""Builders for evaluation tests: planted truth, saved cases, and results with chosen usage."""

from datetime import UTC, datetime, timedelta
from typing import Any

from incident_agent.agent.report import Report
from incident_agent.agent.state import CallRecord, LLMStep, RunResult, UsageTotals
from incident_agent.agent.types import EvidenceRef
from incident_agent.evals.cases import PlannedCase
from incident_agent.evals.scoring import Topology
from incident_agent.evals.types import CaseArtifact, EvalCase, Truth
from tests.agent_support import make_report

MODEL = "gemini:gemini-3.5-flash-lite"
ASKED_AT = datetime(2026, 9, 2, 19, 0, tzinfo=UTC)
CAUSE_AT = datetime(2026, 9, 2, 16, 0, tzinfo=UTC)  # 17:00 Africa/Tunis

TOPOLOGY = Topology(
    parents={
        "CORE-UPF-01": None,
        "CORE-DNS-01": None,
        "AGG-TUN-01": "CORE-UPF-01",
        "LNK-TUN-01-A": "AGG-TUN-01",
        "LNK-TUN-01-B": "AGG-TUN-01",
        "S-TUN-001": "LNK-TUN-01-A",
        "S-TUN-002": "LNK-TUN-01-A",
        "S-TUN-003": "LNK-TUN-01-B",
    }
)


def make_truth(**over: Any) -> Truth:
    base: dict[str, Any] = {
        "kind": "fiber_cut",
        "is_incident": True,
        "root_cause_category": "transport_failure",
        "root_cause_node_id": "LNK-TUN-01-A",
        "start_at": CAUSE_AT,
        "impact_start_at": CAUSE_AT,
        "end_at": CAUSE_AT + timedelta(hours=3),
        "affected_node_ids": ["LNK-TUN-01-A", "S-TUN-001", "S-TUN-002"],
        "affected_region_ids": ["TUN"],
        "severity": "high",
        "difficulty": "easy",
        "evidence": [{"table": "alarms", "id": "ALM-000001", "visible_from": CAUSE_AT.isoformat()}],
        "expected_tools": ["get_alarms", "get_topology", "query_kpis", "search_runbooks"],
        "confounders": [],
        "notes": "Fibre cut.",
    }
    return Truth.model_validate(base | over)


def make_call(
    ref: str, tool: str, *, node: str = "investigate", rows: list[str] | None = None, **over: Any
) -> CallRecord:
    base: dict[str, Any] = {
        "ref": ref,
        "node": node,
        "iteration": 1,
        "tool": tool,
        "args": {},
        "headline": f"{tool} result",
        "body": f"{tool} body",
        "row_refs": rows or [],
        "wall_ms": 100,
    }
    return CallRecord.model_validate(base | over)


def make_result(
    report: Report | None = None,
    *,
    calls: list[CallRecord] | None = None,
    issues: list[str] | None = None,
    steps: list[LLMStep] | None = None,
    error: str | None = None,
    models: list[str] | None = None,
    fell_back: bool = False,
    input_tokens: int = 20_000,
    output_tokens: int = 2_000,
    llm_calls: int = 7,
) -> RunResult:
    report = report or make_report()
    steps = (
        steps
        if steps is not None
        else [
            LLMStep(
                node="investigate",
                purpose="turn",
                provider="gemini",
                model="gemini-3.5-flash-lite",
                latency_ms=1000,
            )
        ]
    )
    evidence = {
        r: EvidenceRef(ref=r, kind="alarm", summary="row") for c in calls or [] for r in c.row_refs
    }
    return RunResult(
        run_id="RUN-test",
        question="Why?",
        asked_at=ASKED_AT,
        status="error" if error else "finished",
        scope=None,
        report=report,
        markdown="",
        usage=UsageTotals(
            llm_calls=llm_calls,
            tool_calls=len([c for c in calls or [] if not c.duplicate_of]),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
        models_used=models if models is not None else [MODEL],
        fell_back=fell_back,
        issues=issues or [],
        error=error,
        steps=steps,
        calls=calls or [],
        evidence=evidence,
    )


def make_case(
    scenario_id: str = "SCN-001", seed: int = 42, question_index: int = 0, **over: Any
) -> EvalCase:
    base: dict[str, Any] = {
        "case_id": f"s{seed}-{scenario_id}-q{question_index}",
        "seed": seed,
        "split": "dev" if seed == 42 else "test",
        "scenario_id": scenario_id,
        "question_index": question_index,
        "question": "Why did traffic drop at S-TUN-001?",
        "asked_at": ASKED_AT,
    }
    return EvalCase.model_validate(base | over)


def make_artifact(
    result: RunResult | None = None,
    *,
    truth: Truth | None = None,
    scenario_id: str = "SCN-001",
    seed: int = 42,
    run_name: str = "test-run",
    variant: str = "default",
    error: str | None = None,
) -> CaseArtifact:
    return CaseArtifact(
        case=make_case(scenario_id, seed),
        truth=truth or make_truth(),
        run_name=run_name,
        variant=variant,
        agent_model=MODEL,
        result=result if result is not None or error else make_result(),
        error=error,
        created_at=datetime(2026, 10, 10, tzinfo=UTC),
    )


def make_planned(
    scenario_id: str, kind: str = "fiber_cut", difficulty: str = "easy", seed: int = 42
) -> PlannedCase:
    return PlannedCase(make_case(scenario_id, seed), make_truth(kind=kind, difficulty=difficulty))
