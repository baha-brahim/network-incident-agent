"""A live investigation: run the agent, stream its events, and store the run when it ends."""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from incident_agent.agent.graph import stream
from incident_agent.agent.reference import Reference
from incident_agent.agent.state import AgentEvent
from incident_agent.agent.tools import execute_tool
from incident_agent.agent.types import ToolContext
from incident_agent.api.enrich import ToolRecorder
from incident_agent.api.events import ApiEvent
from incident_agent.api.kpis import charts_for
from incident_agent.api.runs import Outcome, run_events
from incident_agent.api.services import Services

log = logging.getLogger(__name__)


def day_start(now: datetime) -> datetime:
    """Midnight UTC of the day `now` falls in: the daily limit counts from here."""
    now = now.astimezone(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def seconds_to_next_day(now: datetime) -> int:
    return int((day_start(now) + timedelta(days=1) - now.astimezone(UTC)).total_seconds()) + 1


def live_remaining(svc: Services) -> int:
    used = svc.runs.count_user_runs_since(day_start(svc.clock()))
    return max(0, svc.settings.live_daily_limit - used)


def live_events(svc: Services, question: str, asked_at: datetime) -> Iterator[ApiEvent]:
    """The events of one investigation. Runs the agent as the iterator is consumed.

    When the run ends, its event list is stored. If the iterator is closed before the end (the
    client left), the run is closed as an error in the trace store and nothing else is kept.
    """
    recorder = ToolRecorder(svc.tool_executor or execute_tool, charts_for)
    outcome = Outcome()
    events: list[ApiEvent] = []
    complete = False

    def start() -> Iterator[AgentEvent]:
        agent_engine = svc.agent_engine()
        reference = svc.reference or Reference.load(agent_engine)
        return stream(
            question,
            asked_at,
            runner=svc.runner_factory(),
            ctx=ToolContext(engine=agent_engine, asked_at=asked_at, embedder=svc.embedder),
            store=svc.runs.trace_store(),
            reference=reference,
            tool_executor=recorder,
            trigger="user",
        )

    try:
        for event in run_events(start, recorder, outcome):
            events.append(event)
            complete = event["type"] == "run_finished"
            yield event
    finally:
        _settle(svc, outcome, events, complete)


def _settle(svc: Services, outcome: Outcome, events: list[ApiEvent], complete: bool) -> None:
    run_id = outcome.run_id
    if run_id is None:
        return
    try:
        if complete:
            svc.runs.save_events(run_id, events)
        if not outcome.agent_finished:  # the agent never closed its trace row
            reason = "the investigation crashed" if complete else "the client disconnected"
            svc.runs.mark_stopped(run_id, reason)
    except Exception:
        log.exception("could not store run %s", run_id)
