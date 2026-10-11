"""Fakes for tests that must not touch a network. Used by the runner tests and by the agent tests.

ScriptedRunner: stands in for `LLMRunner` (same `invoke`), answering from a script.

    runner = ScriptedRunner([
        ToolCall(name="get_alarms", args={"start": "2026-09-20"}),   # call 1: one tool call
        [ToolCall(name="get_changes", args={}), ToolCall(name="get_topology", args={})],  # call 2
        "I have enough evidence.",                                   # call 3: plain text
        MyReport(...),                                               # call 4: structured output
        RuntimeError("boom"),                                        # call 5: raises
    ])
    result = runner.invoke([("system", "..."), ("human", "...")], tools=schemas, purpose="step")
    runner.calls    # every call received: .messages, .tools, .schema, .purpose, .index

A script item is a `str` (text), a `ToolCall` or a list of them (tool calls), a pydantic instance or
a dict (structured output; needs `schema=`), a ready `LLMResult`, or an exception (raised). Instead
of a list, pass a function `(RecordedCall) -> item` to decide from the request (for example from
`call.purpose` or `call.schema`). An exhausted list raises `ScriptExhausted`. Canned results report
estimated token counts (chars / 4) and provider/model "scripted".

FakeChatModel: a scripted LangChain chat model (items: str, AIMessage or an exception), for putting
inside a real `LLMRunner` via `ChainEntry("gemini:fake", FakeChatModel(script=[...]))`.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, convert_to_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field

from incident_agent.llm.runner import MessagesInput, ToolSchemas
from incident_agent.llm.types import LLMResult, LLMUsage, ToolCall


class ScriptExhausted(AssertionError):
    """The script had no answer left for a call."""


@dataclass
class RecordedCall:
    index: int
    messages: list[BaseMessage]
    tools: list[dict[str, Any]] | None
    schema: type[BaseModel] | None
    purpose: str
    max_output_tokens: int | None = None

    @property
    def prompt(self) -> str:
        """All message text joined, handy for assertions."""
        return "\n".join(m.text for m in self.messages)


ScriptItem = (
    LLMResult | str | ToolCall | Sequence[ToolCall] | BaseModel | dict[str, Any] | Exception
)


@dataclass
class ScriptedRunner:
    script: Sequence[ScriptItem] | Callable[[RecordedCall], ScriptItem]
    provider: str = "scripted"
    model: str = "scripted"
    calls: list[RecordedCall] = field(default_factory=list)

    def invoke(
        self,
        messages: MessagesInput,
        *,
        tools: ToolSchemas | None = None,
        schema: type[BaseModel] | None = None,
        purpose: str = "",
        max_output_tokens: int | None = None,
    ) -> LLMResult:
        call = RecordedCall(
            index=len(self.calls),
            messages=convert_to_messages(list(messages)),
            tools=list(tools) if tools else None,
            schema=schema,
            purpose=purpose,
            max_output_tokens=max_output_tokens,
        )
        self.calls.append(call)
        if callable(self.script):
            item = self.script(call)
        elif call.index < len(self.script):
            item = self.script[call.index]
        else:
            raise ScriptExhausted(
                f"script has {len(self.script)} items; call {call.index} ({purpose!r})"
            )
        return self._result(item, call)

    def _result(self, item: ScriptItem, call: RecordedCall) -> LLMResult:
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResult):
            return item
        text, tool_calls, parsed = "", [], None
        if isinstance(item, str):
            text = item
        elif isinstance(item, ToolCall):
            tool_calls = [item]
        elif isinstance(item, dict | BaseModel):
            if call.schema is None:
                raise ValueError("a structured script item needs schema= in the call")
            parsed = (
                item
                if isinstance(item, call.schema)
                else call.schema.model_validate(
                    item if isinstance(item, dict) else item.model_dump()
                )
            )
            text = parsed.model_dump_json()
        else:
            tool_calls = list(item)
        chars_in = sum(len(m.text) for m in call.messages)
        usage = LLMUsage(
            provider=self.provider,
            model=self.model,
            input_tokens=chars_in // 4,
            output_tokens=len(text) // 4 + 8 * len(tool_calls),
        )
        return LLMResult(text=text, tool_calls=tool_calls, parsed=parsed, usage=usage)


def ai(
    text: str = "",
    *,
    tool_calls: Sequence[tuple[str, dict[str, Any]]] = (),
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> AIMessage:
    """An AIMessage as a provider would return it (with usage metadata)."""
    return AIMessage(
        content=text,
        tool_calls=[
            {"name": n, "args": a, "id": f"call_{i}", "type": "tool_call"}
            for i, (n, a) in enumerate(tool_calls)
        ],
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )


class FakeChatModel(BaseChatModel):
    """Scripted chat model. Each call pops the next item: str, AIMessage or an exception.

    With `with_structured_output`, the next item's text is parsed as JSON into the schema (a parse
    failure is reported the way LangChain does with include_raw: parsed=None + parsing_error).
    """

    script: list[Any] = Field(default_factory=list)
    seen: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake-scripted"

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        self.seen.append(list(messages))
        if not self.script:
            raise ScriptExhausted("FakeChatModel script is empty")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return ai(item) if isinstance(item, str) else item

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[Any, AIMessage]:
        self.bound_tools.append(list(tools))
        return self

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:
        def run(messages: Any) -> dict[str, Any]:
            raw = self._next(list(messages))
            try:
                return {
                    "raw": raw,
                    "parsed": schema.model_validate_json(raw.text),
                    "parsing_error": None,
                }
            except ValueError as exc:
                return {"raw": raw, "parsed": None, "parsing_error": exc}

        return RunnableLambda(run)
