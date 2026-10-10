"""Shared contracts of the evaluation: a case, its ground truth, the saved run, and grades.

One `CaseArtifact` JSON file per case is the unit everything else reads: scoring, the grader,
the human grading page and the results report.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from incident_agent.agent.state import RunResult

Split = Literal["dev", "test"]  # dev = the world prompts were developed on; test = held out


class EvalCase(BaseModel):
    case_id: str  # s42-SCN-021-q0
    seed: int
    split: Split
    scenario_id: str
    question_index: int
    question: str
    asked_at: datetime  # tz-aware


class Truth(BaseModel):
    """The planted answer for a case. Read from `gt.scenarios`; never shown to the agent."""

    kind: str
    is_incident: bool
    root_cause_category: str
    root_cause_node_id: str | None
    start_at: datetime
    impact_start_at: datetime
    end_at: datetime
    affected_node_ids: list[str]
    affected_region_ids: list[str]
    severity: str
    difficulty: str
    evidence: list[dict[str, Any]]  # [{"table": "alarms", "id": "ALM-000123"}, ...]
    expected_tools: list[str]
    confounders: list[dict[str, Any]]  # [{"table": ..., "id": ..., "why": ...}]
    notes: str = ""


class CaseArtifact(BaseModel):
    """Everything saved about one evaluated case."""

    case: EvalCase
    truth: Truth
    run_name: str  # e.g. baseline-dev
    variant: str  # default | no-gate | no-runbooks | ...
    agent_model: str  # "provider:model" the run was configured with
    result: RunResult | None  # None if the run crashed before producing one
    error: str | None = None  # infrastructure failure (quota, crash), not a wrong answer
    created_at: datetime


FindingVerdict = Literal["supported", "partially_supported", "unsupported", "not_verifiable"]


class FindingGrade(BaseModel):
    index: int  # position in report.findings; -1 = the root-cause statement
    verdict: FindingVerdict
    reason: str = ""


class ReportGrade(BaseModel):
    """A faithfulness judgement of one report, by the grader model or by a person."""

    case_id: str
    grader: str  # "provider:model", or "human:<name>"
    findings: list[FindingGrade]
    comments: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)  # e.g. clarity / actionability scores
