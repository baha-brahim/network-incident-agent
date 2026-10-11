"""Recorded investigations: timing, the library that loads them, and the paced replay."""

import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from incident_agent.api.catalog import CATALOG
from incident_agent.api.events import KEEPALIVE, OPEN, ApiEvent, sse_frame
from incident_agent.api.schemas import DemoCounts, DemoSummary, Recording

DEMOS_DIR = Path(__file__).parent / "demos"
MAX_GAP_MS = 4_000  # the longest pause between two events at speed 1
MIN_STEP_MS = 100  # events are never closer than this, so a replay reads as steps
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def retime(events: list[ApiEvent]) -> list[ApiEvent]:
    """Events with the timing of a real run, rebuilt from what each step took.

    A run replayed from a response cache has almost no model latency. A model call is placed
    after the time it originally took (`latency_ms`), a tool result after its `wall_ms`, and any
    single pause is capped at `MAX_GAP_MS`. `t_ms` is final: a replay only sleeps between them.
    """
    out = deepcopy(events)
    t = 0
    for position, event in enumerate(out):
        data = event["data"]
        pause = 0
        if event["type"] == "llm_call":
            data["wall_ms"] = max(data["wall_ms"], data["latency_ms"])
            pause = data["wall_ms"]
        elif event["type"] == "tool_result":
            pause = data["wall_ms"]
        if position:
            t += max(MIN_STEP_MS, min(pause, MAX_GAP_MS))
        event["t_ms"] = t
    if out and out[-1]["type"] == "run_finished":
        out[-1]["data"]["usage"]["wall_seconds"] = round(t / 1000, 2)
    return out


def counts_of(events: list[ApiEvent]) -> DemoCounts:
    return DemoCounts(
        events=len(events),
        llm_calls=sum(e["type"] == "llm_call" and not e["data"].get("error") for e in events),
        tool_calls=sum(e["type"] == "tool_call" for e in events),
    )


@dataclass(frozen=True)
class LoadedDemo:
    recording: Recording
    events: list[ApiEvent]  # as in the file

    @property
    def summary(self) -> DemoSummary:
        return DemoSummary(**self.recording.model_dump(exclude={"events", "schema_version"}))


class DemoLibrary:
    """The recordings in a directory. Files are read on first use and checked against the schema."""

    def __init__(self, directory: Path = DEMOS_DIR) -> None:
        self.directory = directory
        self._loaded: dict[str, LoadedDemo] = {}

    def ids(self) -> list[str]:
        present = {p.stem for p in self.directory.glob("*.json")}
        ordered = [spec.id for spec in CATALOG if spec.id in present]
        return ordered + sorted(present - set(ordered))

    def get(self, demo_id: str) -> LoadedDemo | None:
        if not _ID.match(demo_id):
            return None
        if demo_id not in self._loaded:
            path = self.directory / f"{demo_id}.json"
            if not path.is_file():
                return None
            self._loaded[demo_id] = load_demo(path)
        return self._loaded[demo_id]

    def all(self) -> list[LoadedDemo]:
        return [demo for i in self.ids() if (demo := self.get(i)) is not None]


def load_demo(path: Path) -> LoadedDemo:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return LoadedDemo(Recording.model_validate(raw), raw["events"])


async def replay_frames(
    events: list[ApiEvent],
    speed: float,
    sleep: Callable[[float], Awaitable[None]],
    keepalive: float,
) -> AsyncIterator[str]:
    """SSE frames of `events`, each sent `(t_ms difference) / speed` after the one before."""
    yield OPEN
    previous = 0
    for event in events:
        remaining = max(0, event["t_ms"] - previous) / 1000 / speed
        previous = event["t_ms"]
        while remaining > 1e-9:
            step = min(remaining, keepalive)
            await sleep(step)
            remaining -= step
            if remaining > 1e-9:
                yield KEEPALIVE
        yield sse_frame(event)
