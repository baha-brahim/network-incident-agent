"""Models of the HTTP API: the events of a run, and the response of every endpoint.

These define `/openapi.json`. Event payloads accept extra fields, so a newer agent can add to them
without breaking old recordings.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from incident_agent.agent.report import Report
from incident_agent.agent.state import UsageTotals
from incident_agent.agent.types import EvidenceKind

# --- events -----------------------------------------------------------------------------------


class Payload(BaseModel):
    model_config = ConfigDict(extra="allow")


class EvidenceItem(Payload):
    """A citable piece of evidence: what a citation chip points to."""

    ref: str
    kind: EvidenceKind
    summary: str


class EvidenceEntry(Payload):
    kind: EvidenceKind
    summary: str


class RunStartedData(Payload):
    question: str
    asked_at: str
    trigger: str


class ScopeData(Payload):
    symptom: str
    window_start: str
    window_end: str
    region_ids: list[str]
    node_ids: list[str]
    nationwide: bool
    ongoing: bool
    source: Literal["model", "default"]
    unknown_ids: list[str]


class LlmCallData(Payload):
    node: str
    purpose: str
    provider: str
    model: str
    served_model: str | None = None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    wall_ms: int
    fell_back: bool
    cached: bool
    attempts: list[str]
    error: str | None = None


class ToolCallData(Payload):
    ref: str
    tool: str
    args: dict[str, Any]
    node: str
    iteration: int


class ToolResultData(Payload):
    ref: str
    tool: str
    headline: str
    error: str | None = None
    n_refs: int
    truncated: bool
    wall_ms: int
    args: dict[str, Any] = Field(
        default_factory=dict, description="Arguments as the tool saw them."
    )
    body: str = Field(default="", description="The compact text the model saw.")
    refs: list[EvidenceItem] = Field(default_factory=list)
    data: Any = Field(default=None, description="Structured payload of the tool, when it has one.")
    data_truncated: bool = False
    duplicate_of: str | None = Field(
        default=None, description="Set when the call repeated an earlier one and was not run."
    )


class NoteData(Payload):
    iteration: int
    text: str


class GateData(Payload):
    missing: list[str]
    message: str


class ReportData(Payload):
    report: Report
    issues: list[str]


class ErrorData(Payload):
    message: str
    where: str | None = None


class RunFinishedData(Payload):
    status: Literal["finished", "error"]
    usage: UsageTotals
    models_used: list[str]
    fell_back: bool
    issues: list[str]
    report: Report
    markdown: str
    evidence: dict[str, EvidenceEntry] = Field(
        default_factory=dict, description="Every reference of the run, by reference."
    )


class _Envelope(BaseModel):
    seq: int = Field(ge=0, description="Position in the run, starting at 0.")
    run_id: str
    t_ms: int = Field(ge=0, description="Milliseconds since the run started.")


class RunStartedEvent(_Envelope):
    type: Literal["run_started"]
    data: RunStartedData


class ScopeEvent(_Envelope):
    type: Literal["scope"]
    data: ScopeData


class LlmCallEvent(_Envelope):
    type: Literal["llm_call"]
    data: LlmCallData


class ToolCallEvent(_Envelope):
    type: Literal["tool_call"]
    data: ToolCallData


class ToolResultEvent(_Envelope):
    type: Literal["tool_result"]
    data: ToolResultData


class NoteEvent(_Envelope):
    type: Literal["note"]
    data: NoteData


class GateEvent(_Envelope):
    type: Literal["gate"]
    data: GateData


class ReportEvent(_Envelope):
    type: Literal["report"]
    data: ReportData


class ErrorEvent(_Envelope):
    type: Literal["error"]
    data: ErrorData


class RunFinishedEvent(_Envelope):
    type: Literal["run_finished"]
    data: RunFinishedData


RunEvent = Annotated[
    RunStartedEvent
    | ScopeEvent
    | LlmCallEvent
    | ToolCallEvent
    | ToolResultEvent
    | NoteEvent
    | GateEvent
    | ReportEvent
    | ErrorEvent
    | RunFinishedEvent,
    Field(discriminator="type"),
]

# --- responses --------------------------------------------------------------------------------


class ErrorBody(BaseModel):
    code: str
    message: str
    fields: list[dict[str, str]] | None = None
    limit: int | None = None
    remaining: int | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool


class RegionInfo(BaseModel):
    id: str
    name: str


class Meta(BaseModel):
    dataset_now: datetime = Field(description="The dataset's 'now': nothing after it is visible.")
    window_start: datetime
    window_end: datetime
    step_minutes: int
    timezone: str
    regions: list[RegionInfo]
    live_enabled: bool
    live_daily_limit: int
    live_remaining: int = Field(description="Live investigations left today (UTC day).")
    model: str = Field(description="The model a live investigation starts with.")


class DemoCounts(BaseModel):
    events: int
    llm_calls: int
    tool_calls: int


class DemoSummary(BaseModel):
    id: str
    title: str
    teaser: str
    question: str
    asked_at: datetime
    duration_ms: int = Field(description="Length of the replay at speed 1.")
    counts: DemoCounts


class Recording(DemoSummary):
    schema_version: Literal[1] = 1
    events: list[RunEvent]


class LiveRequest(BaseModel):
    question: str = Field(description="8 to 300 printable characters.")
    asked_at: datetime | None = Field(
        default=None,
        description="The investigation's 'now'. Defaults to the dataset's now; cannot be later.",
    )

    @field_validator("question")
    @classmethod
    def _question(cls, value: str) -> str:
        text = " ".join(value.split())
        if not 8 <= len(text) <= 300:
            raise ValueError("must be between 8 and 300 characters")
        if not text.isprintable():
            raise ValueError("must be printable text")
        return text


class InvestigationSummary(BaseModel):
    run_id: str
    question: str
    asked_at: datetime
    started_at: datetime
    status: str
    trigger: str
    alert_id: str | None = Field(default=None, description="The detector alert that started it.")
    title: str | None = None
    verdict: str | None = Field(default=None, description="The report's classification.")
    cause: str | None = Field(default=None, description="The report's root cause category.")
    node_id: str | None = None
    confidence: str | None = None
    llm_calls: int | None = None
    tool_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    seconds: float | None = None
    models_used: list[str] = Field(default_factory=list)


class InvestigationDetail(InvestigationSummary):
    report: Report | None = None
    markdown: str | None = None
    issues: list[str] = Field(default_factory=list)
    events: list[RunEvent]


class AlertOut(BaseModel):
    id: str
    start_at: datetime
    end_at: datetime
    severity: str
    score: float
    summary: str
    region_ids: list[str]
    entity_ids: list[str]
    metrics: list[str]
    n_anomalies: int
    status: str
    run_id: str | None = Field(
        default=None, description="The newest stored investigation of this alert, if any."
    )


class AlertRunOut(BaseModel):
    created: bool = Field(
        description="False when the alert was already investigated or is being investigated."
    )
    run: InvestigationSummary


class KpiDeviation(BaseModel):
    direction: Literal["below", "above"]
    onset: datetime
    recovery: datetime | None = Field(description="Null while the deviation is still running.")
    ongoing: bool
    began_before_window: bool


class KpiSeries(BaseModel):
    entity_type: str
    entity_id: str
    metric: str
    unit: str
    start: datetime = Field(description="Time of the first value; later values follow evenly.")
    end: datetime = Field(description="End of the window used, after cutting at the dataset's now.")
    step_minutes: int
    values: list[float | None] = Field(description="Null where no cell reported.")
    baseline: list[float | None] = Field(description="Same length as values; null where unknown.")
    baseline_available: bool
    deviation: KpiDeviation | None = None
    clamped_to_now: bool
    note: str | None = None


class TopoNode(BaseModel):
    id: str
    type: str
    name: str
    region_id: str | None
    parent_id: str | None
    attrs: dict[str, Any]


class Topology(BaseModel):
    node: TopoNode
    chain: list[TopoNode] = Field(description="The node, then its parents up to the core.")
    shared_core: list[TopoNode] = Field(description="Core services every site also depends on.")
    siblings: list[TopoNode]
    n_siblings: int
    children: list[TopoNode]
    n_children: int
    n_sites_below: int
    note: str | None = None
