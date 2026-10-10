"""Knobs of one investigation. Defaults follow the design; tests and ablations override them."""

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    max_iterations: int = Field(default=6, ge=1)  # investigate turns
    max_tool_calls: int = Field(default=14, ge=1)  # tool calls made by the investigate loop
    max_calls_per_iteration: int = Field(default=3, ge=1)
    # If the model wants to stop without having checked the maintenance calendar, the change log
    # and external events for the affected scope and window, nudge it once. Off for ablations.
    completeness_gate: bool = True
    # Tools the model is not told about (ablations).
    disabled_tools: tuple[str, ...] = ()
    max_repairs: int = Field(default=1, ge=0)  # extra LLM calls to fix an invalid report
    # Size limits of what a model sees (characters; the runner estimates ~3.5 characters/token).
    casefile_chars: int = Field(default=7_500, ge=2_000)
    registry_chars: int = Field(default=2_500, ge=0)
    note_chars: int = 700  # one note is cut to this length when it is rendered
    orient_margin_hours: float = 2.0  # how long before the symptom window orient looks for alerts
    default_window_hours: float = 24.0  # used when intake gives no usable window
