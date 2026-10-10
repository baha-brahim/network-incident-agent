"""Live LLM tests (`pytest -m llm`). They use free-tier quota: about 20 provider calls per run.

Set LLM_LIVE_CACHE_DIR to record responses and make re-runs free; unset, every run calls the
providers.
"""

import json
import os
import re
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from incident_agent.config import get_settings
from incident_agent.llm.factory import make_chat_model
from incident_agent.llm.runner import LLMRunner
from incident_agent.llm.types import LLMResult

PROMPT = "Reply with one short sentence."

GEMINI = "gemini:gemini-3.5-flash-lite"
GROQ = "groq:openai/gpt-oss-120b"
GROQ_QWEN = "groq:qwen/qwen3.8-27b"
OLLAMA = "ollama:qwen3:4b"


def _invoke(spec: str) -> None:
    answer = make_chat_model(spec).invoke(PROMPT).text
    assert answer.strip()


@pytest.mark.llm
def test_gemini_live() -> None:
    if get_settings().gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY not set")
    _invoke(get_settings().agent_model)


@pytest.mark.llm
def test_groq_live() -> None:
    if get_settings().groq_api_key is None:
        pytest.skip("GROQ_API_KEY not set")
    _invoke("groq:openai/gpt-oss-120b")


@pytest.mark.llm
def test_ollama_live() -> None:
    _invoke("ollama:qwen3:4b")


# --- the runner against real providers ------------------------------------------------------------


class GetAlarmsArgs(BaseModel):
    start: str = Field(description="ISO 8601 start of the window")
    end: str = Field(description="ISO 8601 end of the window")
    node_ids: list[str] | None = Field(default=None, description="Restrict to these nodes")
    region_id: str | None = None
    include_descendants: bool = True
    min_severity: Literal["minor", "major", "critical"] | None = None


TOOLS = [
    {
        "name": "get_alarms",
        "description": "List alarms in a time window, optionally for given nodes.",
        "parameters": GetAlarmsArgs.model_json_schema(),
    }
]

SYSTEM = "You are a telecom network incident analyst. Be concise."


class TimelineItem(BaseModel):
    time: str
    event: str
    refs: list[str]


class Finding(BaseModel):
    claim: str
    refs: list[str]


class Hypothesis(BaseModel):
    category: Literal["transport_failure", "power_failure", "bad_change", "capacity", "unknown"]
    node_id: str | None = None
    verdict: Literal["confirmed", "rejected", "unresolved"]
    reason: str
    refs: list[str]


class DismissedSignal(BaseModel):
    ref: str
    reason: str


class Report(BaseModel):
    """Same shape as the agent's report: enums, nullable fields, lists of small objects."""

    title: str
    classification: Literal[
        "incident", "planned_maintenance", "expected_event", "no_impact", "inconclusive"
    ]
    root_cause_category: Literal[
        "transport_failure", "power_failure", "bad_change", "capacity", "no_impact", "unknown"
    ]
    root_cause_node_id: str | None = None
    root_cause_summary: str
    confidence: Literal["low", "medium", "high"]
    impact_summary: str
    impact_start: str | None = None
    impact_end: str | None = None
    affected_node_ids: list[str]
    timeline: list[TimelineItem]
    findings: list[Finding]
    hypotheses: list[Hypothesis]
    dismissed_signals: list[DismissedSignal]
    recommended_actions: list[str]


CASE = """Question: Why did traffic drop in region Tunis between 02:00 and 05:00 on 2026-09-21?
T1 get_anomalies -> Alert ALR-0008 02:10: DL traffic -62% on 5 sites S-TUN-011..015 (region R-TUN).
T2 get_alarms -> ALM-000224 02:09 critical LOS on LNK-TUN-02-C (cleared 05:20); ALM-000230 02:11 \
sites unreachable behind LNK-TUN-02-C.
T3 get_maintenance -> MW-0003 planned window on S-TUN-040 at 03:00 (unrelated node).
T4 search_runbooks -> RB-FIBER-CUT#03: LOS on a transport link with downstream sites unreachable \
indicates a fiber cut.
Write the incident report. Cite refs such as T2, ALM-000224, MW-0003, RB-FIBER-CUT#03."""

ALARM_RESULT = (
    "T1 get_alarms(node_ids=['LNK-TUN-02-C']) -> 1 alarm: ALM-000224 critical LOS on LNK-TUN-02-C, "
    "raised 2026-09-21 02:09, cleared 2026-09-21 05:20."
)

PROVIDERS = {"gemini": GEMINI, "groq": GROQ, "ollama": OLLAMA}


def _runner(*chain: str) -> LLMRunner:
    """A runner over the given models. LLM_LIVE_CACHE_DIR turns on recording (re-runs are free).

    Recordings do not depend on the model, so each first model gets its own folder; otherwise
    one provider's recording would answer for another.
    """
    root = os.environ.get("LLM_LIVE_CACHE_DIR")
    folder = re.sub(r"[^A-Za-z0-9._-]", "_", chain[0])
    return LLMRunner(
        chain=list(chain),
        cache_mode="readwrite" if root else "off",
        cache_dir=Path(root) / folder if root else None,
    )


def _require(spec: str) -> None:
    settings = get_settings()
    if spec.startswith("gemini:") and settings.gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY not set")
    if spec.startswith("groq:") and settings.groq_api_key is None:
        pytest.skip("GROQ_API_KEY not set")


def _ask_for_alarms(runner: LLMRunner) -> LLMResult:
    question = (
        "List the critical alarms on node LNK-TUN-02-C "
        "between 2026-09-21 01:00 and 2026-09-21 06:00."
    )
    return runner.invoke([("system", SYSTEM), ("human", question)], tools=TOOLS, purpose="tool")


@pytest.mark.llm
@pytest.mark.parametrize("provider", PROVIDERS)
def test_plain_text(provider: str) -> None:
    _require(PROVIDERS[provider])
    result = _runner(PROVIDERS[provider]).invoke(
        [("system", "Be terse."), ("human", "Reply with exactly: pong")], purpose="plain"
    )
    assert "pong" in result.text.lower()
    assert result.usage.input_tokens > 0 and result.usage.output_tokens > 0
    assert not result.usage.fell_back


@pytest.mark.llm
@pytest.mark.parametrize("provider", PROVIDERS)
def test_tool_call(provider: str) -> None:
    _require(PROVIDERS[provider])
    result = _ask_for_alarms(_runner(PROVIDERS[provider]))
    assert [c.name for c in result.tool_calls] == ["get_alarms"]
    args = result.tool_calls[0].args
    assert isinstance(args, dict) and "LNK-TUN-02-C" in json.dumps(args)
    GetAlarmsArgs.model_validate(args)  # the arguments fit the tool's own schema


@pytest.mark.llm
@pytest.mark.parametrize("spec", [GEMINI, GROQ, GROQ_QWEN, OLLAMA])
def test_structured_report(spec: str) -> None:
    _require(spec)
    result = _runner(spec).invoke(
        [("system", SYSTEM), ("human", CASE)], schema=Report, purpose="report"
    )
    report = result.parsed
    assert isinstance(report, Report)
    assert report.classification == "incident"
    assert report.root_cause_category == "transport_failure"
    assert report.timeline and report.findings


@pytest.mark.llm
def test_forced_fallback_from_a_nonexistent_model() -> None:
    _require(GEMINI)
    _require(GROQ)
    result = _runner("gemini:no-such-model-xyz", GROQ).invoke(
        [("system", "Be terse."), ("human", "Reply with exactly: pong")], purpose="fallback"
    )
    assert "pong" in result.text.lower()
    assert result.usage.fell_back and result.usage.provider == "groq"
    assert [a.status for a in result.usage.attempts] == ["error", "ok"]
    assert "no-such-model-xyz" in result.usage.attempts[0].model


ROUND_TRIPS = [(GEMINI, GROQ), (GROQ, OLLAMA), (OLLAMA, GEMINI), (OLLAMA, OLLAMA)]


@pytest.mark.llm
@pytest.mark.parametrize(("first", "second"), ROUND_TRIPS)
def test_stateless_round_trip(first: str, second: str) -> None:
    """Call 1 asks for a tool; call 2 is a fresh prompt with the tool's result as plain text.

    No tool-call message is replayed, and a different provider may answer the second call.
    """
    _require(first)
    _require(second)
    call = _ask_for_alarms(_runner(first)).tool_calls
    assert call and call[0].name == "get_alarms"

    follow_up = (
        "Question: Which node had a critical LOS alarm, and when was it cleared?\n"
        f"{ALARM_RESULT}\nAnswer in one sentence using the evidence above."
    )
    result = _runner(second).invoke(
        [("system", SYSTEM), ("human", follow_up)], purpose="round trip"
    )
    assert not result.tool_calls
    assert "LNK-TUN-02-C" in result.text and "05:20" in result.text
