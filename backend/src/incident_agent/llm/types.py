"""Result and error types of the LLM runner."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """A tool call, normalised across providers. `args` is always a dict (never a JSON string)."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class Attempt(BaseModel):
    """One model the runner tried (or skipped) while answering a call."""

    model: str  # "provider:model"
    status: Literal["ok", "error", "skipped"]
    error: str | None = None  # scrubbed of secrets and truncated
    latency_ms: int = 0
    raw: str | None = None  # the model's unparseable answer, kept for diagnosis and salvage


class LLMUsage(BaseModel):
    provider: str  # the model that actually answered
    model: str
    input_tokens: int = 0
    output_tokens: int = 0  # as the provider reports it; may include reasoning tokens
    latency_ms: int = 0
    served_model: str | None = None  # what the provider says it ran (aliases move)
    attempts: list[Attempt] = Field(default_factory=list)  # every model tried, in order
    fell_back: bool = False  # true if the answer did not come from the first model of the chain
    cached: bool = False  # true if replayed from the cache (the other fields describe the original)


class LLMResult(BaseModel):
    text: str = ""  # the model's text content ("" if none)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    parsed: BaseModel | None = None  # an instance of the requested schema
    usage: LLMUsage


class LLMError(Exception):
    """Base class of runner errors."""


class AllModelsFailed(LLMError):
    """Every model of the chain failed or was skipped. `attempts` says why, per model."""

    def __init__(self, attempts: list[Attempt]) -> None:
        self.attempts = attempts
        lines = [f"{a.model}: {a.status}" + (f" ({a.error})" if a.error else "") for a in attempts]
        super().__init__("All models failed: " + "; ".join(lines or ["no model in the chain"]))

    @property
    def raw_output(self) -> str | None:
        """The last unparseable answer among the attempts, if any."""
        return next((a.raw for a in reversed(self.attempts) if a.raw), None)


class CacheMiss(LLMError):
    """Replay mode found no recording for this request."""

    def __init__(self, key: str, purpose: str, preview: str) -> None:
        self.key = key
        super().__init__(
            f"No cached LLM response for key {key[:16]} (purpose={purpose!r}): {preview!r}"
        )


class MalformedOutput(LLMError):
    """A provider answered, but not in a usable shape (bad tool call, invalid structured output).

    `raw` is the text of the answer when there was one (a cut-off JSON document, for example).
    """

    def __init__(self, message: str, raw: str | None = None) -> None:
        super().__init__(message)
        self.raw = raw
