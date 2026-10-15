"""The investigation graph and the entry points `investigate` and `stream`.

    intake (LLM) -> orient (code) -> investigate (LLM + tools, loops) -> conclude (LLM)
        -> verify (code; a repair call for citation problems, one for look-alike problems)
        -> render (code)

Nodes announce what they do through LangGraph's custom stream; `stream` yields those events and
`investigate` runs the same generator to the end and returns the result.
"""

import re
import time
import uuid
from collections.abc import Callable, Generator, Iterator
from datetime import datetime
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from incident_agent.agent import nodes
from incident_agent.agent.config import AgentConfig
from incident_agent.agent.nodes import Deps, ToolExecutor
from incident_agent.agent.reference import Reference
from incident_agent.agent.report import Report, fallback_report
from incident_agent.agent.state import (
    AgentEvent,
    AgentState,
    RunResult,
    UsageTotals,
)
from incident_agent.agent.store import TraceStore
from incident_agent.agent.tools import execute_tool
from incident_agent.agent.tools.timeutil import as_utc
from incident_agent.agent.types import ToolContext
from incident_agent.llm.runner import LLMRunner, Runner


def build_graph(deps: Deps) -> Any:
    """Compile the graph. `deps` carries the runner, tool context, config and trace store."""
    g: StateGraph[AgentState, Any, Any, Any] = StateGraph(AgentState)
    for name in ("intake", "orient", "investigate", "conclude", "verify", "render"):
        g.add_node(name, partial(getattr(nodes, name), deps=deps))
    g.add_edge(START, "intake")
    g.add_edge("intake", "orient")
    g.add_edge("orient", "investigate")
    g.add_conditional_edges("investigate", nodes.route_after_investigate)
    g.add_edge("conclude", "verify")
    g.add_edge("verify", "render")
    g.add_edge("render", END)
    return g.compile()


_ATTEMPT = re.compile(r"^(.*?): (ok|error|skipped)\b")


def usage_totals(state: AgentState, wall_seconds: float) -> UsageTotals:
    totals = UsageTotals(wall_seconds=round(wall_seconds, 2))
    for step in state.steps:
        if not step.cached:  # every attempt that reached a provider used some of its quota
            for line in step.attempts:
                match = _ATTEMPT.match(line)
                if match and match.group(2) != "skipped":
                    totals.live_requests[match.group(1)] = (
                        totals.live_requests.get(match.group(1), 0) + 1
                    )
        if step.error:
            continue
        totals.llm_calls += 1
        totals.input_tokens += step.input_tokens
        totals.output_tokens += step.output_tokens
        if step.cached:
            totals.cached_calls += 1
    totals.tool_calls = sum(1 for c in state.calls if not c.duplicate_of)
    return totals


def models_used(state: AgentState) -> list[str]:
    seen: list[str] = []
    for step in state.steps:
        if not step.error and f"{step.provider}:{step.model}" not in seen:
            seen.append(f"{step.provider}:{step.model}")
    return seen


def _run_id() -> str:
    return "RUN-" + uuid.uuid4().hex[:10]


def _result(state: AgentState, started: float) -> RunResult:
    report = state.report or fallback_report(state.error or "no report", [])
    return RunResult(
        run_id=state.run_id,
        question=state.question,
        asked_at=state.asked_at,
        status="error" if state.error else "finished",
        scope=state.scope,
        report=report,
        report_before_checks=state.report_before_checks,
        markdown=state.markdown,
        usage=usage_totals(state, time.perf_counter() - started),
        models_used=models_used(state),
        fell_back=any(s.fell_back for s in state.steps),
        issues=state.issues,
        error=state.error,
        steps=state.steps,
        calls=state.calls,
        evidence=state.evidence,
    )


def _run(
    question: str,
    asked_at: datetime,
    *,
    runner: Runner | None,
    ctx: ToolContext | None,
    store: TraceStore | None,
    config: AgentConfig | None,
    reference: Reference | None,
    tool_executor: ToolExecutor | None,
    trigger: str,
    alert_id: str | None,
) -> Generator[AgentEvent, None, RunResult]:
    cfg = config or AgentConfig()
    asked = as_utc(asked_at)
    if ctx is None:
        from incident_agent.db.session import get_agent_engine

        ctx = ToolContext(engine=get_agent_engine(), asked_at=asked)
    ctx = ctx.model_copy(update={"asked_at": asked})
    deps = Deps(
        runner=runner or LLMRunner("agent"),
        ctx=ctx,
        config=cfg,
        reference=reference or Reference.load(ctx.engine),
        execute=tool_executor or execute_tool,
        store=store,
    )
    state = AgentState(run_id=_run_id(), question=question, asked_at=asked)
    started = time.perf_counter()
    start_event = AgentEvent(
        type="run_started",
        run_id=state.run_id,
        data={"question": question, "asked_at": asked.isoformat(), "trigger": trigger},
    )
    yield start_event
    if store is not None:
        try:
            store.start_run(
                state.run_id, question, asked, trigger=trigger, alert_id=alert_id,
                config=cfg.model_dump(),
            )  # fmt: skip
        except Exception as exc:
            deps.store = None  # a broken store must not stop the investigation
            state.issues.append(f"trace store disabled: {type(exc).__name__}: {str(exc)[:200]}")

    graph = build_graph(deps)
    final: Any = state
    try:
        for mode, chunk in graph.stream(
            state, stream_mode=["custom", "values"], config={"recursion_limit": 60}
        ):
            if mode == "custom":
                yield chunk
            else:
                final = chunk
    except Exception as exc:
        state.error = f"{type(exc).__name__}: {str(exc)[:300]}"
        yield AgentEvent(type="error", run_id=state.run_id, data={"message": state.error})
        final = state
    final_state = final if isinstance(final, AgentState) else AgentState.model_validate(final)
    result = _result(final_state, started)
    if deps.store is not None:
        try:
            deps.store.finish_run(result)
        except Exception as exc:
            result.issues.append(f"trace store: {type(exc).__name__}: {str(exc)[:200]}")
    yield AgentEvent(
        type="run_finished",
        run_id=state.run_id,
        data={
            "status": result.status,
            "usage": result.usage.model_dump(),
            "models_used": result.models_used,
            "fell_back": result.fell_back,
            "issues": result.issues,
            "report": result.report.model_dump(mode="json"),
            "markdown": result.markdown,
        },
    )
    return result


def stream(
    question: str,
    asked_at: datetime,
    *,
    runner: Runner | None = None,
    ctx: ToolContext | None = None,
    store: TraceStore | None = None,
    config: AgentConfig | None = None,
    reference: Reference | None = None,
    tool_executor: ToolExecutor | None = None,
    trigger: str = "user",
    alert_id: str | None = None,
) -> Iterator[AgentEvent]:
    """Run an investigation, yielding events as they happen. The last one is `run_finished`."""
    return _run(
        question, asked_at, runner=runner, ctx=ctx, store=store, config=config,
        reference=reference, tool_executor=tool_executor, trigger=trigger, alert_id=alert_id,
    )  # fmt: skip


def investigate(
    question: str,
    asked_at: datetime,
    *,
    runner: Runner | None = None,
    ctx: ToolContext | None = None,
    store: TraceStore | None = None,
    config: AgentConfig | None = None,
    on_event: Callable[[AgentEvent], None] | None = None,
    reference: Reference | None = None,
    tool_executor: ToolExecutor | None = None,
    trigger: str = "user",
    alert_id: str | None = None,
) -> RunResult:
    """Investigate `question` as of `asked_at` and return the report with usage and provenance."""
    gen = _run(
        question, asked_at, runner=runner, ctx=ctx, store=store, config=config,
        reference=reference, tool_executor=tool_executor, trigger=trigger, alert_id=alert_id,
    )  # fmt: skip
    while True:
        try:
            event = next(gen)
        except StopIteration as done:
            result: RunResult = done.value
            return result
        if on_event is not None:
            on_event(event)


__all__ = ["Report", "build_graph", "investigate", "stream"]
