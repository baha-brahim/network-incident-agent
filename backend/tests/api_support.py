"""Helpers for the API tests: an in-memory run repository, scripted services, an SSE parser."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import StaticPool

from incident_agent.agent.store import TraceStore
from incident_agent.api.demos import DemoLibrary
from incident_agent.api.events import ApiEvent
from incident_agent.api.schemas import InvestigationDetail, InvestigationSummary
from incident_agent.api.services import Services
from incident_agent.config import Settings
from incident_agent.llm.testing import ScriptedRunner
from incident_agent.llm.types import ToolCall
from tests.agent_support import REFERENCE, WINDOW, fake_tools, make_report, script_for

DATASET_NOW = "2026-09-03T08:00:00+00:00"
QUESTION = "Why did traffic drop at S-TUN-001 this afternoon?"


def sqlite_engine() -> Engine:
    """An in-memory database shared by every thread, holding the dataset facts the API reads."""
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE dataset_meta (key text, value text)"))
        conn.execute(text("CREATE TABLE regions (region_id text, name text)"))
        for key, value in {
            "now": DATASET_NOW,
            "window_start": "2026-08-31T23:00:00+00:00",
            "window_end": "2026-09-04T23:00:00+00:00",
            "step_minutes": "15",
            "timezone": "Africa/Tunis",
        }.items():
            conn.execute(text("INSERT INTO dataset_meta VALUES (:k, :v)"), {"k": key, "v": value})
        conn.execute(text("INSERT INTO regions VALUES ('TUN', 'Grand Tunis'), ('SFX', 'Sfax')"))
    return engine


class MemoryTraceStore(TraceStore):
    """Notes in the repository which runs the agent started and how they ended."""

    def __init__(self, repo: "MemoryRunRepository") -> None:
        self.repo = repo

    def start_run(  # type: ignore[override]
        self, run_id: str, question: str, asked_at: datetime, *, trigger: str = "user",
        alert_id: str | None = None, config: Any = None,
    ) -> None:  # fmt: skip
        started = datetime.now(UTC)
        self.repo.runs[run_id] = {
            "question": question, "asked_at": asked_at, "started_at": started,
            "trigger": trigger, "alert_id": alert_id, "status": "running",
        }  # fmt: skip
        if trigger == "alert":
            self.repo.alert_runs.append(started)

    def log_step(self, *args: Any, **kwargs: Any) -> None:
        pass

    def finish_run(self, result: Any) -> None:
        self.repo.runs[result.run_id]["status"] = result.status

    def fail_run(self, run_id: str, error: str) -> None:
        self.repo.runs[run_id]["status"] = "error"


class MemoryRunRepository:
    """Keeps live runs in a dict, standing in for the Postgres repository when no database runs."""

    def __init__(self) -> None:
        self.events: dict[str, list[ApiEvent]] = {}
        self.runs: dict[str, dict[str, Any]] = {}  # every run the agent started, in order
        self.user_runs: list[datetime] = []  # start times that count against the daily limit
        self.alert_runs: list[datetime] = []  # the same for alert-triggered runs
        self.stopped: list[tuple[str, str]] = []

    def trace_store(self) -> TraceStore | None:
        return MemoryTraceStore(self)

    def count_user_runs_since(self, since: datetime) -> int:
        return sum(1 for t in self.user_runs if t >= since)

    def count_alert_runs_since(self, since: datetime) -> int:
        return sum(1 for t in self.alert_runs if t >= since)

    def save_events(self, run_id: str, events: list[ApiEvent]) -> None:
        self.events[run_id] = events
        if events[0]["data"]["trigger"] == "user":
            self.user_runs.append(datetime.now(UTC))

    def mark_stopped(self, run_id: str, reason: str) -> None:
        self.stopped.append((run_id, reason))
        if run_id in self.runs:
            self.runs[run_id]["status"] = "error"

    def get_summary(self, run_id: str) -> InvestigationSummary | None:
        if run_id in self.events:
            return self._summary(run_id)
        info = self.runs.get(run_id)
        if info is None:
            return None
        return InvestigationSummary(run_id=run_id, **info)

    def find_alert_run(self, alert_id: str, running_since: datetime) -> InvestigationSummary | None:
        for run_id, info in reversed(self.runs.items()):
            alive = info["status"] == "running" and info["started_at"] >= running_since
            if info["alert_id"] == alert_id and (info["status"] == "finished" or alive):
                return self.get_summary(run_id)
        return None

    def latest_alert_run_ids(
        self, alert_ids: list[str], *, stored_only: bool = False
    ) -> dict[str, str]:
        latest: dict[str, str] = {}
        for run_id, info in self.runs.items():
            if info["alert_id"] in alert_ids and (run_id in self.events or not stored_only):
                latest[info["alert_id"]] = run_id
        return latest

    def _summary(self, run_id: str) -> InvestigationSummary:
        events = self.events[run_id]
        started, finished = events[0]["data"], events[-1]["data"]
        report = finished["report"]
        usage = finished["usage"]
        return InvestigationSummary(
            run_id=run_id,
            question=started["question"],
            asked_at=started["asked_at"],
            started_at=self.runs.get(run_id, {}).get("started_at", datetime.now(UTC)),
            status=finished["status"],
            trigger=started["trigger"],
            alert_id=self.runs.get(run_id, {}).get("alert_id"),
            title=report["title"],
            verdict=report["classification"],
            cause=report["root_cause_category"],
            node_id=report["root_cause_node_id"],
            confidence=report["confidence"],
            llm_calls=usage["llm_calls"],
            tool_calls=usage["tool_calls"],
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            seconds=usage["wall_seconds"],
            models_used=finished["models_used"],
        )

    def list_runs(self, limit: int) -> list[InvestigationSummary]:
        return [self._summary(r) for r in reversed(list(self.events))][:limit]

    def get_run(self, run_id: str) -> InvestigationDetail | None:
        if run_id not in self.events:
            return None
        finished = self.events[run_id][-1]["data"]
        return InvestigationDetail(
            **self._summary(run_id).model_dump(),
            report=finished["report"],
            markdown=finished["markdown"],
            issues=finished["issues"],
            events=self.events[run_id],
        )


def calls(*tools: str) -> list[ToolCall]:
    return [ToolCall(name=t, args=dict(WINDOW)) for t in tools]


def default_script() -> Callable[..., Any]:
    """Two checks, a repeated call, then the report: a run with every kind of tool event."""
    turns: list[list[ToolCall] | str] = [
        [*calls("get_alarms", "get_maintenance"), *calls("get_alarms")],
        [*calls("get_changes", "get_external_events")],
        "Link alarm explains it; calendar clear.",
    ]
    return script_for(turns, make_report())


def make_services(
    tmp_path: Path | None = None,
    *,
    script: Callable[..., Any] | None = None,
    repo: MemoryRunRepository | None = None,
    demos: Path | None = None,
    **settings: Any,
) -> Services:
    from incident_agent.api.demos import DEMOS_DIR

    engine = sqlite_engine()
    return Services(
        settings=Settings(_env_file=None, **settings),
        engine=lambda: engine,
        agent_engine=lambda: engine,
        repo=repo or MemoryRunRepository(),
        demos=DemoLibrary(demos or DEMOS_DIR),
        runner_factory=lambda: ScriptedRunner(script or default_script()),
        tool_executor=fake_tools,
        reference=REFERENCE,
        keepalive_seconds=0.05,
    )


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    """(event name, parsed data) of every frame; comment lines are skipped."""
    frames: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        lines = [line for line in block.split("\n") if line and not line.startswith(":")]
        if not lines:
            continue
        assert lines[0].startswith("event: ") and lines[1].startswith("data: "), block
        assert len(lines) == 2, block
        frames.append((lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])))
    return frames
