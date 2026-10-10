"""Shared types for scenario sampling, injection and placement."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from incident_agent.simulator.config import SimConfig
from incident_agent.simulator.events import EventLog, Handle
from incident_agent.simulator.kpis import Baseline, Effects
from incident_agent.simulator.timeaxis import TimeAxis
from incident_agent.simulator.topology import Topology


@dataclass
class Ctx:
    cfg: SimConfig
    axis: TimeAxis
    topo: Topology
    base: Baseline
    fx: Effects
    log: EventLog
    rng: np.random.Generator
    used: dict[str, int] = field(default_factory=dict)  # how often a target was chosen


@dataclass
class Params:
    """Everything decided about a scenario before it is given a start time."""

    kind: str
    difficulty: str
    duration: pd.Timedelta  # total footprint, from the start time to the end of any effect
    start_hours: tuple[float, float]  # local start window; hi may exceed 24
    regions: list[str]
    data: dict[str, Any] = field(default_factory=dict)
    whole_day: bool = False  # starts at local midnight and blocks the whole day
    weekday_only: bool = False


@dataclass
class ScenarioDraft:
    kind: str
    is_incident: bool
    category: str
    root_node: str | None
    start: pd.Timestamp
    impact_start: pd.Timestamp
    end: pd.Timestamp
    affected_nodes: list[str]
    regions: list[str]
    severity: str
    difficulty: str
    evidence: list[Handle]
    expected_tools: list[str]
    notes: str
    confounders: list[tuple[Handle, str]] = field(default_factory=list)
    block_nodes: list[str] = field(default_factory=list)  # nodes noise must avoid around it
    group: str | None = None
    affected_sites: list[str] = field(default_factory=list)  # used for question text


@dataclass(frozen=True)
class ScenarioKind:
    name: str
    is_incident: bool
    sample: Callable[[Ctx, str], Params]
    apply: Callable[[Ctx, Params, pd.Timestamp], ScenarioDraft]
