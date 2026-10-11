"""One investigation as the web interface sees it: numbered, timed and enriched events."""

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from incident_agent.agent.report import fallback_report
from incident_agent.agent.state import AgentEvent, RunResult, UsageTotals
from incident_agent.api.enrich import ToolRecorder, evidence_map, tool_result_extras
from incident_agent.api.events import ApiEvent, envelope
from incident_agent.api.jsonsafe import to_jsonable

log = logging.getLogger(__name__)

UNKNOWN_RUN = "RUN-unknown"


@dataclass
class Outcome:
    """What `run_events` learned about the run, for the caller to act on after the last event."""

    run_id: str | None = None
    agent_finished: bool = False  # the agent itself closed the run (and its trace row)


def _crash_message(exc: Exception) -> str:
    if isinstance(exc, SQLAlchemyError):
        return "The database is unavailable."
    return "The investigation failed unexpectedly."


def _crash_finish(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "usage": UsageTotals().model_dump(),
        "models_used": [],
        "fell_back": False,
        "issues": [message],
        "report": fallback_report(message, []).model_dump(mode="json"),
        "markdown": "",
        "evidence": {},
    }


def _finish_data(agent_data: dict[str, Any], result: RunResult | None) -> dict[str, Any]:
    data = to_jsonable(agent_data)
    if "evidence" not in data:
        data["evidence"] = evidence_map(result.evidence) if result is not None else {}
    return data  # type: ignore[no-any-return]


def run_events(
    start: Callable[[], Iterator[AgentEvent]],
    recorder: ToolRecorder,
    outcome: Outcome | None = None,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> Iterator[ApiEvent]:
    """Run `start()` (the agent's event stream) and yield API events with `t_ms` from `clock`.

    Never raises: a failure of the run itself becomes an `error` event and a `run_finished` with
    status "error". Closing the iterator closes the agent's stream.
    """
    outcome = outcome if outcome is not None else Outcome()
    t0 = clock()
    seq = 0
    call_args: dict[str, dict[str, Any]] = {}

    def make(type_: str, data: dict[str, Any]) -> ApiEvent:
        nonlocal seq
        event = envelope(
            seq, type_, outcome.run_id or UNKNOWN_RUN, round((clock() - t0) * 1000), data
        )
        seq += 1
        return event

    stream: Iterator[AgentEvent] | None = None
    try:
        stream = start()
        for agent_event in stream:
            outcome.run_id = agent_event.run_id
            data = to_jsonable(agent_event.data)
            if agent_event.type == "tool_call":
                call_args[data["ref"]] = data["args"]
            elif agent_event.type == "tool_result":
                args = call_args.get(data["ref"], {})
                recorded = recorder.take(data["tool"], args)
                data = {**tool_result_extras(recorded, args, data["headline"]), **data}
            elif agent_event.type == "run_finished":
                result = _result_of(stream)
                outcome.agent_finished = True
                yield make("run_finished", _finish_data(data, result))
                return
            yield make(agent_event.type, data)
    except Exception as exc:
        log.exception("investigation failed")
        message = _crash_message(exc)
        yield make("error", {"where": "run", "message": message})
        yield make("run_finished", _crash_finish(message))
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            close()


def _result_of(stream: Iterator[AgentEvent]) -> RunResult | None:
    """The agent returns its `RunResult` right after the last event; read it without a new event."""
    try:
        next(stream)
    except StopIteration as done:
        value = done.value
        return value if isinstance(value, RunResult) else None
    except Exception:
        log.exception("could not read the run result")
    return None
