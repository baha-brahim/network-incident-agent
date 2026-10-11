"""The state of one investigation: scope, call log, evidence registry, notes, usage, report."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from incident_agent.agent.report import Report
from incident_agent.agent.types import EvidenceRef


class Scope(BaseModel):
    """What the question is about, resolved by intake and clamped by code."""

    symptom: str
    window_start: datetime  # tz-aware
    window_end: datetime  # never after asked_at
    region_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    nationwide: bool = False
    ongoing: bool = False
    source: Literal["model", "default"] = "model"  # "default" = intake gave nothing usable
    unknown_ids: list[str] = Field(default_factory=list)  # named ids that are not in the network


class CallRecord(BaseModel):
    """One tool call of the run. `ref` is the call reference (T1, T2, ...) the report may cite."""

    ref: str
    node: str  # orient | investigate
    iteration: int
    tool: str
    args: dict[str, Any]
    headline: str
    body: str
    error: str | None = None
    truncated: bool = False
    row_refs: list[str] = Field(default_factory=list)  # ids of the rows the call returned
    duplicate_of: str | None = None
    wall_ms: int = 0


class Note(BaseModel):
    iteration: int
    text: str
    source: Literal["model", "gate", "system"] = "model"


class LLMStep(BaseModel):
    """One LLM call: which model answered, what it cost."""

    node: str  # intake | investigate | conclude | repair
    purpose: str
    provider: str
    model: str
    served_model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0  # as the provider call took (the original call, if replayed from cache)
    wall_ms: int = 0  # time this run waited for it
    fell_back: bool = False
    cached: bool = False
    attempts: list[str] = Field(default_factory=list)  # "model: status (error)" per attempt
    error: str | None = None
    raw_output: str | None = None  # an unparseable structured answer, kept for diagnosis


class AgentState(BaseModel):
    run_id: str
    question: str
    asked_at: datetime
    scope: Scope | None = None
    calls: list[CallRecord] = Field(default_factory=list)
    evidence: dict[str, EvidenceRef] = Field(default_factory=dict)
    notes: list[Note] = Field(default_factory=list)
    steps: list[LLMStep] = Field(default_factory=list)
    iteration: int = 0  # investigate turns taken
    tool_calls_used: int = 0  # investigate-phase tool calls (counts against the cap)
    gate_fired: bool = False
    investigating: bool = True
    report: Report | None = None
    markdown: str = ""
    issues: list[str] = Field(default_factory=list)
    error: str | None = None


class UsageTotals(BaseModel):
    llm_calls: int = 0
    cached_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    wall_seconds: float = 0.0
    live_requests: dict[str, int] = Field(default_factory=dict)  # model spec -> requests sent


class RunResult(BaseModel):
    run_id: str
    question: str
    asked_at: datetime
    status: Literal["finished", "error"]
    scope: Scope | None
    report: Report
    markdown: str
    usage: UsageTotals
    models_used: list[str]  # "provider:model" of every step, in first-use order
    fell_back: bool
    issues: list[str]  # verification problems and run problems
    error: str | None = None
    steps: list[LLMStep]
    calls: list[CallRecord]
    evidence: dict[str, EvidenceRef]


EventType = Literal[
    "run_started",
    "scope",
    "tool_call",
    "tool_result",
    "note",
    "gate",
    "llm_call",
    "report",
    "error",
    "run_finished",
]


class AgentEvent(BaseModel):
    """Something that happened during a run, in order. M6 forwards these over SSE."""

    type: EventType
    run_id: str
    data: dict[str, Any] = Field(default_factory=dict)
