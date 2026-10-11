"""Everything the endpoints depend on, built lazily so importing the app connects to nothing."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Engine

from incident_agent.agent.nodes import ToolExecutor
from incident_agent.agent.reference import Reference
from incident_agent.api.datasets import DatasetFacts, dataset_facts
from incident_agent.api.demos import DEMOS_DIR, DemoLibrary
from incident_agent.api.repository import PgRunRepository, RunRepository
from incident_agent.config import Settings
from incident_agent.db.session import get_agent_engine, get_engine
from incident_agent.llm.runner import LLMRunner, Runner
from incident_agent.rag.embedder import Embedder


def _default_runner() -> Runner:
    return LLMRunner("agent")


@dataclass
class Services:
    settings: Settings
    engine: Callable[[], Engine] = get_engine  # owner role: the `app` schema
    agent_engine: Callable[[], Engine] = get_agent_engine  # read-only role: the network data
    repo: RunRepository | None = None
    demos: DemoLibrary = field(default_factory=lambda: DemoLibrary(DEMOS_DIR))
    runner_factory: Callable[[], Runner] = _default_runner
    tool_executor: ToolExecutor | None = None  # None: the agent's own tools
    reference: Reference | None = None  # None: read from the database for each run
    embedder: Embedder | None = None  # None: the default embedder
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    keepalive_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.repo is None:
            self.repo = PgRunRepository(self.engine)

    @property
    def runs(self) -> RunRepository:
        assert self.repo is not None
        return self.repo

    def facts(self) -> DatasetFacts:
        return dataset_facts(self.agent_engine())
