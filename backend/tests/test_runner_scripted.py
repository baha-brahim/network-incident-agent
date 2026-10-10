from typing import Literal

import pytest
from pydantic import BaseModel

from incident_agent.llm.runner import Runner
from incident_agent.llm.testing import RecordedCall, ScriptedRunner, ScriptExhausted
from incident_agent.llm.types import ToolCall

MSGS = [("system", "sys"), ("human", "Why did traffic drop?")]


class Out(BaseModel):
    verdict: Literal["yes", "no"]


def test_list_script_serves_each_kind_in_order() -> None:
    call = ToolCall(name="get_alarms", args={"a": 1})
    r = ScriptedRunner(["text", call, [call, call], Out(verdict="yes"), {"verdict": "no"}])
    assert r.invoke(MSGS).text == "text"
    assert r.invoke(MSGS).tool_calls == [call]
    assert len(r.invoke(MSGS).tool_calls) == 2
    assert r.invoke(MSGS, schema=Out).parsed == Out(verdict="yes")
    assert r.invoke(MSGS, schema=Out).parsed == Out(verdict="no")
    assert [c.index for c in r.calls] == [0, 1, 2, 3, 4]


def test_exhausted_script_and_exceptions() -> None:
    r = ScriptedRunner([RuntimeError("boom")])
    with pytest.raises(RuntimeError, match="boom"):
        r.invoke(MSGS)
    with pytest.raises(ScriptExhausted):
        r.invoke(MSGS, purpose="extra")


def test_callable_script_sees_the_request() -> None:
    def script(call: RecordedCall) -> str:
        return "tools" if call.tools else f"{call.purpose}:{call.prompt.count('traffic')}"

    r = ScriptedRunner(script)
    assert r.invoke(MSGS, purpose="intake").text == "intake:1"
    assert r.invoke(MSGS, tools=[{"name": "t"}]).text == "tools"
    assert r.calls[1].tools == [{"name": "t"}]


def test_usage_is_filled_and_runner_protocol_fits() -> None:
    r: Runner = ScriptedRunner(["x" * 40])
    usage = r.invoke(MSGS).usage
    assert (usage.provider, usage.model, usage.output_tokens) == ("scripted", "scripted", 10)
    assert usage.input_tokens > 0 and not usage.fell_back and not usage.cached


def test_structured_item_needs_a_schema() -> None:
    with pytest.raises(ValueError, match="schema"):
        ScriptedRunner([Out(verdict="yes")]).invoke(MSGS)
