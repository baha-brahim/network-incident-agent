"""The LLM runner: one call in, one normalised result out, whatever provider answers.

Every call is stateless: the caller passes a fresh `[system, human]` pair (tool results from earlier
steps are plain text inside the human message). The runner walks a chain of models (primary, then
fallbacks) and records every attempt.

Decisions on provider output:
- A tool call whose arguments cannot be parsed into a dict (invalid JSON, not an object, no name),
  a structured output that fails validation, and an empty answer (no text and no tool call) are
  failed attempts and move to the next model.
- A tool call naming a tool that was not offered is returned as-is: the caller decides (the agent
  reports the error back to the model). Arguments are not checked against the tool schema either;
  `execute_tool` turns validation errors into a `ToolResult.error`.
- Arguments that arrive as a JSON string are decoded.
"""

import json
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, convert_to_messages
from pydantic import BaseModel

from incident_agent.config import Settings, get_settings
from incident_agent.llm.cache import ResponseCache, cache_key, request_description
from incident_agent.llm.errors import classify, scrub
from incident_agent.llm.factory import chain_specs, make_chat_model, parse_model_spec
from incident_agent.llm.types import (
    AllModelsFailed,
    Attempt,
    CacheMiss,
    LLMResult,
    LLMUsage,
    MalformedOutput,
    ToolCall,
)

MessagesInput = Sequence[BaseMessage | tuple[str, str]]
ToolSchemas = Sequence[dict[str, Any]]

HOSTED_TIMEOUT_S = 45.0
OLLAMA_TIMEOUT_S = 180.0  # the first call also loads the model
OLLAMA_NUM_CTX = 12288  # ~1.8 GB of KV cache for a 4B model: fits a 6 GB GPU
OLLAMA_MAX_OUTPUT_TOKENS = 4096  # qwen3 thinks before answering; leave room for it
DEFAULT_MAX_OUTPUT_TOKENS = 2048
MAX_RAW_CHARS = 20_000  # an unparseable answer is kept this long on its attempt
CHARS_PER_TOKEN = 3.5  # deliberately pessimistic, so size checks err on the side of skipping


@dataclass(frozen=True)
class ProviderLimits:
    max_request_tokens: int | None  # estimated input + requested output must fit
    throttled: bool  # enforce the minimum interval between calls
    max_output_tokens: int | None = None  # overrides the runner's default


LIMITS: dict[str, ProviderLimits] = {
    "gemini": ProviderLimits(None, True),
    "groq": ProviderLimits(8000, True),  # free tier: 8k tokens per request (and per minute)
    "ollama": ProviderLimits(
        OLLAMA_NUM_CTX, False, OLLAMA_MAX_OUTPUT_TOKENS
    ),  # beyond the context window it truncates
}
DEFAULT_LIMITS = ProviderLimits(None, True)

# Output controls that make a chat model deterministic and cheap. See `build_model_kwargs`.
STRUCTURED_METHOD: dict[str, Literal["json_schema", "function_calling"]] = {
    "gemini": "json_schema",
    "groq": "json_schema",
    "ollama": "json_schema",
}


@dataclass
class ChainEntry:
    """One model of the chain. `model` is injected in tests; otherwise it is built on first use."""

    spec: str  # "provider:model"
    model: BaseChatModel | None = None  # when set (tests), used for every call
    built: dict[int, BaseChatModel] = field(default_factory=dict)  # clients by output budget

    @property
    def provider(self) -> str:
        return parse_model_spec(self.spec)[0]

    @property
    def name(self) -> str:
        return parse_model_spec(self.spec)[1]


class Runner(Protocol):
    """What the agent needs from a runner. `LLMRunner` and `testing.ScriptedRunner` both fit."""

    def invoke(
        self,
        messages: MessagesInput,
        *,
        tools: ToolSchemas | None = None,
        schema: type[BaseModel] | None = None,
        purpose: str = "",
        max_output_tokens: int | None = None,
    ) -> LLMResult: ...


def build_model_kwargs(
    provider: str,
    model: str,
    *,
    max_output_tokens: int,
    timeout: float | None = None,
    reasoning: bool = False,
) -> dict[str, Any]:
    """Client settings for one provider: temperature 0, no internal retries, reasoning turned down.

    Reasoning controls (checked against the installed langchain packages and live):
    - gemini 3.x: `thinking_level="minimal"` (the lowest; thinking cannot be switched off).
      Older models: `thinking_budget=0`.
    - groq gpt-oss: `reasoning_effort="low"` (gpt-oss cannot disable reasoning).
      Groq qwen3: `reasoning_effort="none"`.
    - ollama qwen3:4b cannot stop thinking: with think=false it still reasons and puts the text
      in the answer (ending in a bare `</think>`). So `reasoning=True`, which makes Ollama return
      the thinking separately and the answer clean (same token count, no leak).
    Gemini 3.5 ignores `temperature` (fixed sampling), so it is not sent there.

    `reasoning=True` turns reasoning back on for Groq models (qwen: effort "high", gpt-oss:
    "medium"; the thinking text is hidden from the answer but still counts as output tokens). It
    changes nothing for the other providers. Checked live on qwen/qwen3.8-27b: effort "default"
    produced no reasoning tokens at all, "high" does.
    """
    if provider == "gemini":
        kwargs: dict[str, Any] = {
            "max_output_tokens": max_output_tokens,
            "timeout": timeout or HOSTED_TIMEOUT_S,
            "max_retries": 1,  # total attempts: no internal retry
        }
        if "gemini-3.5" not in model:
            kwargs["temperature"] = 0.0
        kwargs.update(
            {"thinking_level": "minimal"} if "gemini-3" in model else {"thinking_budget": 0}
        )
        return kwargs
    if provider == "groq":
        kwargs = {
            "temperature": 0.0,
            "max_tokens": max_output_tokens,
            "timeout": timeout or HOSTED_TIMEOUT_S,
            "max_retries": 0,
        }
        if "gpt-oss" in model:
            kwargs["reasoning_effort"] = "medium" if reasoning else "low"
        elif "qwen" in model:
            kwargs["reasoning_effort"] = "high" if reasoning else "none"
            if reasoning:
                kwargs["reasoning_format"] = "hidden"
        return kwargs
    return {
        "temperature": 0.0,
        "num_predict": max_output_tokens,
        "num_ctx": OLLAMA_NUM_CTX,
        "reasoning": True,
        "client_kwargs": {"timeout": timeout or OLLAMA_TIMEOUT_S},
    }


def estimate_tokens(
    messages: Sequence[BaseMessage], tools: ToolSchemas | None, schema: type[BaseModel] | None
) -> int:
    chars = sum(len(m.text) for m in messages)
    chars += len(json.dumps(list(tools or []), default=str))
    chars += len(json.dumps(schema.model_json_schema())) if schema else 0
    return int(chars / CHARS_PER_TOKEN) + 1


def _invalid_structured(raw: Any, error: Any) -> MalformedOutput:
    """Describe a structured answer that did not validate; the reason comes first.

    Error texts are cut to a few hundred characters downstream, and the parser's message starts
    with the whole answer, so lead with the finish reason and the end of the parser's complaint.
    """
    meta = getattr(raw, "response_metadata", None) or {}
    usage = getattr(raw, "usage_metadata", None) or {}
    detail = ", ".join(
        part
        for part in (
            f"finish_reason={meta['finish_reason']}" if meta.get("finish_reason") else "",
            f"{usage['output_tokens']} output tokens" if usage.get("output_tokens") else "",
        )
        if part
    )
    why = " ".join(str(error).split())
    why = why.rsplit(" Got: ", 1)[-1] if " Got: " in why else why[-160:]
    text = getattr(raw, "text", None)
    return MalformedOutput(
        f"structured output invalid ({detail or 'no metadata'}): {why[:160]}",
        raw=text if isinstance(text, str) and text else None,
    )


def _tool_calls(raw: AIMessage) -> list[ToolCall]:
    if raw.invalid_tool_calls:
        bad = raw.invalid_tool_calls[0]
        raise MalformedOutput(f"malformed tool call {bad.get('name')!r}: {bad.get('error')}")
    calls = []
    for call in raw.tool_calls:
        args: Any = call.get("args")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError as exc:
                raise MalformedOutput(
                    f"tool call {call.get('name')!r}: arguments not JSON"
                ) from exc
        if args is None:
            args = {}
        if not call.get("name") or not isinstance(args, dict):
            raise MalformedOutput(f"malformed tool call: {call.get('name')!r} args={type(args)}")
        calls.append(ToolCall(name=call["name"], args=_clean(args)))
    return calls


# gpt-oss writes non-breaking hyphens (U+2011) and narrow no-break spaces (U+202F) inside IDs and
# times, which would break exact matching downstream.
_LOOKALIKES = str.maketrans(
    {0x2010: "-", 0x2011: "-", 0x00A0: " ", 0x2009: " ", 0x202F: " ", 0x200A: " "}
)


def _clean(value: Any) -> Any:
    """Replace look-alike hyphens and spaces by plain ones in every string of a JSON-like value."""
    if isinstance(value, str):
        return value.translate(_LOOKALIKES)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


def _text(raw: AIMessage) -> str:
    text = re.sub(r"<think>.*?</think>", "", raw.text, flags=re.DOTALL)
    text = text.rsplit("</think>", 1)[-1]  # a stray closing tag: all before it is thinking
    return str(_clean(text.strip()))


class _Throttle:
    """Minimum interval between two calls to the same model; thread-safe."""

    def __init__(self, clock: Callable[[], float], sleep: Callable[[float], None]) -> None:
        self._clock, self._sleep = clock, sleep
        self._next_free: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, model: str, interval: float) -> None:
        with self._lock:
            now = self._clock()
            start = max(now, self._next_free.get(model, now))
            self._next_free[model] = start + interval
        if start > now:
            self._sleep(start - now)


class LLMRunner:
    """Chain of models with fallback, cooldowns, size checks, throttling and a response cache.

    Args:
        role: "agent" (primary + fallbacks from settings) or "grader" (the grader model only).
        chain: model specs ("provider:model") or `ChainEntry`s (with an injected chat model);
            overrides the settings. Models are built lazily, so replay needs no API keys.
        route: optional `call_index -> specs`: the ordered models to try for that call (each must
            be in the chain). Lets a test force a different provider per call.
        cache_mode / cache_dir / min_interval_seconds: override the settings.
        reasoning: leave reasoning on for models that allow switching it (see `build_model_kwargs`).
            The cache key does not include it, so keep runs with different settings in different
            `cache_dir`s.
        clock / sleep: injectable for tests (throttle and cooldown use them).
    """

    def __init__(
        self,
        role: Literal["agent", "grader"] = "agent",
        *,
        chain: Sequence[str | ChainEntry] | None = None,
        settings: Settings | None = None,
        cache_mode: Literal["off", "readwrite", "replay"] | None = None,
        cache_dir: Path | None = None,
        min_interval_seconds: float | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        reasoning: bool = False,
        route: Callable[[int], Sequence[str]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.role = role
        self.settings = settings or get_settings()
        specs = chain if chain is not None else chain_specs(role, self.settings)
        self.chain = [e if isinstance(e, ChainEntry) else ChainEntry(e) for e in specs]
        self.cache_mode = cache_mode or self.settings.llm_cache_mode
        self.cache = ResponseCache(cache_dir or self.settings.llm_cache_dir)
        self.min_interval = (
            self.settings.llm_min_interval_seconds
            if min_interval_seconds is None
            else min_interval_seconds
        )
        self.max_output_tokens = max_output_tokens
        self.reasoning = reasoning
        self.route = route
        self._clock = clock
        self._throttle = _Throttle(clock, sleep)
        self._cooldown_until: dict[str, float] = {}
        self._calls = 0
        self._secrets = [
            k.get_secret_value()
            for k in (self.settings.gemini_api_key, self.settings.groq_api_key)
            if k is not None
        ]

    # --- public ---------------------------------------------------------------------------

    def invoke(
        self,
        messages: MessagesInput,
        *,
        tools: ToolSchemas | None = None,
        schema: type[BaseModel] | None = None,
        purpose: str = "",
        max_output_tokens: int | None = None,
    ) -> LLMResult:
        """Answer one stateless call. `tools` are {name, description, parameters} dicts.

        `max_output_tokens` replaces the runner's default for this call only (the size check and
        the client both use it). It is not part of the cache key: a recording replays whatever
        budget it was made with.

        Returns text, normalised tool calls, and (when `schema` is given) a validated instance.
        Raises `CacheMiss` (replay mode) or `AllModelsFailed`.
        """
        if tools and schema:
            raise ValueError("tools and schema cannot be combined in one call")
        msgs = convert_to_messages(list(messages))
        call_index, self._calls = self._calls, self._calls + 1

        description = request_description(self.role, msgs, tools, schema, purpose)
        key = cache_key(description)
        if self.cache_mode != "off":
            if (hit := self.cache.load(key, schema)) is not None:
                return hit
            if self.cache_mode == "replay":
                raise CacheMiss(key, purpose, description["prompt_preview"])

        result = self._run_chain(msgs, tools, schema, call_index, max_output_tokens)
        if self.cache_mode == "readwrite":
            self.cache.save(key, description, result)
        return result

    # --- chain ----------------------------------------------------------------------------

    def _ordered(self, call_index: int) -> list[ChainEntry]:
        if self.route is None:
            return self.chain
        by_spec = {e.spec: e for e in self.chain}
        return [by_spec[s] for s in self.route(call_index)]

    def _output_tokens(self, provider: str, requested: int | None = None) -> int:
        """Output budget of a call: the request, else the runner default. A provider's own
        setting (ollama leaves room for its thinking) is a floor."""
        budget = requested or self.max_output_tokens
        return max(budget, LIMITS.get(provider, DEFAULT_LIMITS).max_output_tokens or 0)

    def _skip_reason(self, entry: ChainEntry, prompt_tokens: int, output: int) -> str | None:
        wait = self._cooldown_until.get(entry.spec, 0.0) - self._clock()
        if wait > 0:
            return f"cooling down for {wait:.0f}s after an error"
        limit = LIMITS.get(entry.provider, DEFAULT_LIMITS).max_request_tokens
        if limit is not None and prompt_tokens + output > limit:
            return f"request too large: ~{prompt_tokens} prompt + {output} output tokens > {limit}"
        return None

    def _run_chain(
        self,
        msgs: list[BaseMessage],
        tools: ToolSchemas | None,
        schema: type[BaseModel] | None,
        call_index: int,
        max_output_tokens: int | None = None,
    ) -> LLMResult:
        prompt_tokens = estimate_tokens(msgs, tools, schema)
        attempts: list[Attempt] = []
        order = self._ordered(call_index)
        for entry in order:
            budget = self._output_tokens(entry.provider, max_output_tokens)
            if reason := self._skip_reason(entry, prompt_tokens, budget):
                attempts.append(Attempt(model=entry.spec, status="skipped", error=reason))
                continue
            if LIMITS.get(entry.provider, DEFAULT_LIMITS).throttled and self.min_interval > 0:
                self._throttle.wait(entry.spec, self.min_interval)
            started = time.perf_counter()
            try:
                result = self._call(entry, msgs, tools, schema, budget)
            except Exception as exc:
                ms = round((time.perf_counter() - started) * 1000)
                info = classify(exc)
                if info.cooldown:
                    self._cooldown_until[entry.spec] = self._clock() + info.cooldown
                error = scrub(f"{type(exc).__name__}: {exc}", self._secrets)
                raw = getattr(exc, "raw", None)
                attempts.append(
                    Attempt(
                        model=entry.spec,
                        status="error",
                        error=error,
                        latency_ms=ms,
                        raw=raw[:MAX_RAW_CHARS] if isinstance(raw, str) else None,
                    )
                )
                continue
            ms = round((time.perf_counter() - started) * 1000)
            attempts.append(Attempt(model=entry.spec, status="ok", latency_ms=ms))
            result.usage.latency_ms = ms
            result.usage.attempts = attempts
            result.usage.fell_back = entry.spec != order[0].spec
            return result
        raise AllModelsFailed(attempts)

    # --- one provider call ----------------------------------------------------------------

    def _chat_model(self, entry: ChainEntry, output_tokens: int) -> BaseChatModel:
        if entry.model is not None:
            return entry.model
        if output_tokens not in entry.built:
            kwargs = build_model_kwargs(
                entry.provider,
                entry.name,
                max_output_tokens=output_tokens,
                reasoning=self.reasoning,
            )
            entry.built[output_tokens] = make_chat_model(entry.spec, **kwargs)
        return entry.built[output_tokens]

    def _call(
        self,
        entry: ChainEntry,
        msgs: list[BaseMessage],
        tools: ToolSchemas | None,
        schema: type[BaseModel] | None,
        output_tokens: int,
    ) -> LLMResult:
        chat = self._chat_model(entry, output_tokens)
        parsed: BaseModel | None = None
        if schema is not None:
            method = STRUCTURED_METHOD.get(entry.provider, "json_schema")
            out: Any = chat.with_structured_output(schema, method=method, include_raw=True).invoke(
                msgs
            )
            raw, parsed_out, error = out["raw"], out.get("parsed"), out.get("parsing_error")
            if error is not None or parsed_out is None:
                raise _invalid_structured(raw, error)
            if not isinstance(parsed_out, schema):
                parsed_out = schema.model_validate(parsed_out)
            parsed = schema.model_validate(_clean(parsed_out.model_dump()))
        else:
            runnable = chat.bind_tools(list(tools)) if tools else chat
            raw = runnable.invoke(msgs)
        if not isinstance(raw, AIMessage):
            raise MalformedOutput(f"unexpected response type {type(raw).__name__}")

        text, calls = _text(raw), _tool_calls(raw)
        if parsed is None and not text and not calls:
            raise MalformedOutput("empty response")
        usage: Any = raw.usage_metadata or {}
        meta = raw.response_metadata or {}
        return LLMResult(
            text=text,
            tool_calls=calls,
            parsed=parsed,
            usage=LLMUsage(
                provider=entry.provider,
                model=entry.name,
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                served_model=meta.get("model_version")
                or meta.get("model_name")
                or meta.get("model"),
            ),
        )
