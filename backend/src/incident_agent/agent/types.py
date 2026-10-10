"""Shared contracts of the agent: what a tool returns and how evidence is referenced."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Engine

from incident_agent.rag.embedder import Embedder

EvidenceKind = Literal[
    "alert",  # ALR-0008
    "anomaly",  # ANM-000123
    "alarm",  # ALM-000224
    "change",  # CHG-2026-0044
    "maintenance",  # MW-0003
    "event",  # EVT-002
    "runbook",  # RB-FIBER-CUT#03
    "node",  # S-TUN-012, LNK-TUN-02-C (a topology fact about that node)
    "call",  # T3: the tool call itself (KPI queries, SQL, topology lookups)
]


class EvidenceRef(BaseModel):
    """One citable piece of evidence. `ref` is what a report cites."""

    ref: str
    kind: EvidenceKind
    summary: str  # one line, enough to recognise it without re-reading the tool output


class ToolResult(BaseModel):
    """What every tool returns. Only `headline` and `body` are shown to the model."""

    tool: str
    args: dict[str, Any]
    headline: str  # one line; kept in the case file after `body` has been trimmed away
    body: str  # compact text for the model, at most ~500 tokens
    refs: list[EvidenceRef] = Field(default_factory=list)
    data: Any = None  # structured payload for the UI and evals; never sent to the model
    truncated: bool = False  # true if rows were cut to fit the budget (say so in `body`)
    error: str | None = None  # set instead of raising, so the model can react


class ToolContext(BaseModel):
    """Passed to every tool. Tools never see data after `asked_at`."""

    model_config = {"arbitrary_types_allowed": True}

    engine: Engine  # must be the read-only agent_ro engine
    asked_at: datetime  # tz-aware; the investigation's "now"
    embedder: Embedder | None = None  # for search_runbooks; default embedder if None
