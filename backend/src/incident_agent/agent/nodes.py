"""The nodes of the investigation graph: intake, orient, investigate, conclude, verify, render."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from langgraph.config import get_stream_writer
from pydantic import BaseModel

from incident_agent.agent import prompts
from incident_agent.agent.casefile import conclude_message, render_case_file
from incident_agent.agent.checks import missing_checks
from incident_agent.agent.config import AgentConfig
from incident_agent.agent.facts import Facts, rows_of
from incident_agent.agent.lookalike import lookalike_problems
from incident_agent.agent.reference import Reference
from incident_agent.agent.report import (
    MAX_FINDINGS,
    Finding,
    Report,
    fallback_report,
    is_partial,
    limit_report,
    render_markdown,
)
from incident_agent.agent.salvage import NOTE as PARTIAL_NOTE
from incident_agent.agent.salvage import salvage_report
from incident_agent.agent.state import (
    AgentEvent,
    AgentState,
    CallRecord,
    LLMStep,
    Note,
    Scope,
)
from incident_agent.agent.store import TraceStore
from incident_agent.agent.tools import execute_tool, tool_schemas
from incident_agent.agent.tools.timeutil import TimeParseError, as_utc, fmt, parse_time, to_local
from incident_agent.agent.types import EvidenceRef, ToolContext, ToolResult
from incident_agent.agent.verify import (
    cap_confidence,
    check_faithfulness,
    check_report,
    strip_invalid,
)
from incident_agent.llm.runner import Runner
from incident_agent.llm.types import Attempt, LLMResult

ToolExecutor = Callable[[str, dict[str, Any], ToolContext], ToolResult]
MAX_RAW_KEPT = 12_000  # characters of an unparseable answer kept on its step


class IntakeOutput(BaseModel):
    """Structured output of intake. Times are strings so a bad one can be replaced, not rejected."""

    symptom: str
    window_start: str | None
    window_end: str | None
    region_ids: list[str]
    node_ids: list[str]
    nationwide: bool
    ongoing: bool


@dataclass
class Deps:
    runner: Runner
    ctx: ToolContext
    config: AgentConfig
    reference: Reference
    execute: ToolExecutor = execute_tool
    store: TraceStore | None = None
    seq: int = 0  # steps written to the trace so far
    store_errors: list[str] = field(default_factory=list)


def emit(state: AgentState, type_: str, **data: Any) -> None:
    """Send an event on LangGraph's custom stream; a no-op outside a running graph."""
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer(AgentEvent.model_validate({"type": type_, "run_id": state.run_id, "data": data}))


# --- helpers ----------------------------------------------------------------------------------


def _parse(value: str | None) -> datetime | None:
    if not value or not value.strip() or value.strip().lower() in {"null", "none"}:
        return None
    try:
        return parse_time(value)
    except TimeParseError:
        return None


def build_scope(out: IntakeOutput, asked_at: datetime, deps: Deps) -> Scope:
    """Clamp the model's window to `asked_at`; default to the previous day when it is unusable."""
    asked = as_utc(asked_at)
    default_start = asked - timedelta(hours=deps.config.default_window_hours)
    start, end = _parse(out.window_start), _parse(out.window_end)
    source: Literal["model", "default"] = "model"
    if out.ongoing:
        end = asked
    if start is None and end is None:
        start, end, source = default_start, asked, "default"
    elif start is None:
        assert end is not None
        start = end - timedelta(hours=deps.config.default_window_hours)
    elif end is None:
        end = asked
    assert start is not None and end is not None
    end = min(end, asked)
    if start >= end:
        start, end, source = default_start, asked, "default"
    ref = deps.reference
    regions = [
        r for r in dict.fromkeys(x.strip().upper() for x in out.region_ids) if r in ref.regions
    ]
    nodes: list[str] = []
    unknown: list[str] = []
    for raw in out.node_ids:
        found = ref.canonical(raw)
        if found is None:
            unknown.append(raw)
        elif found in ref.regions:
            if found not in regions:
                regions.append(found)
        elif found not in nodes:
            nodes.append(found)
    return Scope(
        symptom=out.symptom.strip() or "unspecified symptom",
        window_start=start,
        window_end=end,
        region_ids=regions,
        node_ids=nodes,
        nationwide=out.nationwide,
        ongoing=out.ongoing,
        source=source,
        unknown_ids=unknown,
    )


def _step_from(node: str, purpose: str, result: LLMResult, wall_ms: int) -> LLMStep:
    u = result.usage
    return LLMStep(
        node=node,
        purpose=purpose,
        provider=u.provider,
        model=u.model,
        served_model=u.served_model,
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        latency_ms=u.latency_ms,
        wall_ms=wall_ms,
        fell_back=u.fell_back,
        cached=u.cached,
        attempts=_attempt_lines(u.attempts),
    )


def _attempt_lines(attempts: list[Attempt]) -> list[str]:
    return [f"{a.model}: {a.status}" + (f" ({a.error[:120]})" if a.error else "") for a in attempts]


def _call_llm(
    deps: Deps,
    state: AgentState,
    node: str,
    purpose: str,
    system: str,
    human: str,
    *,
    tools: list[dict[str, Any]] | None = None,
    schema: type[BaseModel] | None = None,
    max_output_tokens: int | None = None,
) -> tuple[LLMResult | None, LLMStep]:
    """One stateless model call. A failure is recorded as a step with an error, not raised."""
    started = time.perf_counter()
    result: LLMResult | None = None
    try:
        result = deps.runner.invoke(
            [("system", system), ("human", human)],
            tools=tools,
            schema=schema,
            purpose=purpose,
            max_output_tokens=max_output_tokens,
        )
    except Exception as exc:
        raw = getattr(exc, "raw_output", None) or getattr(exc, "raw", None)
        wall = round((time.perf_counter() - started) * 1000)
        step = LLMStep(
            node=node,
            purpose=purpose,
            provider="-",
            model="-",
            wall_ms=wall,
            attempts=_attempt_lines(getattr(exc, "attempts", [])),
            error=f"{type(exc).__name__}: {str(exc)[:400]}",
            raw_output=raw[:MAX_RAW_KEPT] if isinstance(raw, str) else None,
        )
    else:
        wall = round((time.perf_counter() - started) * 1000)
        step = _step_from(node, purpose, result, wall)
    _trace(
        deps,
        state,
        "llm",
        node,
        purpose,
        {"system_chars": len(system), "message": human[:20000]},
        {"text": (result.text if result else "")[:4000]}
        | ({"parsed": result.parsed.model_dump(mode="json")} if result and result.parsed else {})
        | ({"tool_calls": [c.model_dump() for c in result.tool_calls]} if result else {}),
        step,
    )
    emit(state, "llm_call", **step.model_dump())
    return result, step


def _trace(
    deps: Deps,
    state: AgentState,
    kind: str,
    node: str,
    name: str,
    input_: dict[str, Any],
    output: dict[str, Any],
    step: LLMStep | None = None,
    call: CallRecord | None = None,
) -> None:
    if deps.store is None:
        return
    deps.seq += 1
    try:
        deps.store.log_step(
            state.run_id, deps.seq, kind, node, name, input_, output, step=step, call=call
        )
    except Exception as exc:  # the trace is a convenience: never fail the investigation for it
        msg = f"trace store: {type(exc).__name__}: {str(exc)[:200]}"
        if msg not in deps.store_errors:
            deps.store_errors.append(msg)


def _run_tool(
    deps: Deps,
    state: AgentState,
    calls: list[CallRecord],
    evidence: dict[str, EvidenceRef],
    facts: dict[str, dict[str, Any]],
    node: str,
    iteration: int,
    name: str,
    args: dict[str, Any],
) -> CallRecord:
    """Execute one tool call, assign its T-ref, register its evidence and rows.

    Appends to `calls`; `evidence` and `facts` are updated in place.
    """
    ref = f"T{len(calls) + 1}"
    key = json.dumps([name, args], sort_keys=True, default=str)
    earlier = next(
        (
            c
            for c in calls
            if c.error is None and json.dumps([c.tool, c.args], sort_keys=True, default=str) == key
        ),
        None,
    )
    emit(state, "tool_call", ref=ref, tool=name, args=args, node=node, iteration=iteration)
    started = time.perf_counter()
    if earlier is not None:
        record = CallRecord(
            ref=ref,
            node=node,
            iteration=iteration,
            tool=name,
            args=args,
            headline=f"Identical to {earlier.ref}; not run again. Use {earlier.ref}.",
            body=f"Identical to {earlier.ref}; not run again.",
            duplicate_of=earlier.ref,
        )
        result = None
    else:
        result = deps.execute(name, args, deps.ctx)
        record = CallRecord(
            ref=ref,
            node=node,
            iteration=iteration,
            tool=name,
            args=result.args if isinstance(result.args, dict) else args,
            headline=result.headline,
            body=result.body,
            error=result.error,
            truncated=result.truncated,
            row_refs=[r.ref for r in result.refs],
            wall_ms=round((time.perf_counter() - started) * 1000),
        )
        for row in result.refs:
            evidence[row.ref] = row
        if not result.error:
            facts.update(rows_of(name, result.data))
    args_text = ", ".join(f"{k}={v}" for k, v in record.args.items() if v not in (None, [], ""))
    evidence[ref] = EvidenceRef(
        ref=ref, kind="call", summary=f"{name}({args_text})"[:150] + f" -> {record.headline}"[:200]
    )
    calls.append(record)
    emit(
        state,
        "tool_result",
        ref=ref,
        tool=name,
        headline=record.headline,
        error=record.error,
        n_refs=len(record.row_refs),
        truncated=record.truncated,
        wall_ms=record.wall_ms,
    )
    _trace(
        deps,
        state,
        "tool",
        node,
        name,
        {"ref": ref, "args": record.args},
        {
            "headline": record.headline,
            "body": record.body,
            "refs": [r.ref for r in result.refs] if result else [],
            "error": record.error,
        },
        call=record,
    )
    return record


# --- nodes ------------------------------------------------------------------------------------


def intake(state: AgentState, deps: Deps) -> dict[str, Any]:
    asked = to_local(state.asked_at)
    human = (
        f"Current time: {fmt(state.asked_at)} ({asked.strftime('%A')}). "
        f"Yesterday was {(asked - timedelta(days=1)).strftime('%Y-%m-%d (%A)')}.\n"
        f"Question: {state.question}"
    )
    result, step = _call_llm(
        deps, state, "intake", "intake", prompts.intake_system(deps.reference), human,
        schema=IntakeOutput,
    )  # fmt: skip
    issues = list(state.issues)
    if result is None or not isinstance(result.parsed, IntakeOutput):
        issues.append(f"intake failed, default scope used: {step.error}")
        parsed = IntakeOutput(
            symptom=state.question[:120],
            window_start=None,
            window_end=None,
            region_ids=[],
            node_ids=[],
            nationwide=False,
            ongoing=False,
        )
    else:
        parsed = result.parsed
    scope = build_scope(parsed, state.asked_at, deps)
    emit(state, "scope", **scope.model_dump(mode="json"))
    return {"scope": scope, "steps": [*state.steps, step], "issues": issues}


def orient(state: AgentState, deps: Deps) -> dict[str, Any]:
    scope = state.scope
    assert scope is not None
    calls = list(state.calls)
    evidence = dict(state.evidence)
    facts = dict(state.facts)
    margin = timedelta(hours=deps.config.orient_margin_hours)
    args: dict[str, Any] = {
        "start": fmt(scope.window_start - margin),
        "end": fmt(state.asked_at),
    }
    if len(scope.node_ids) == 1:
        args["entity_id"] = scope.node_ids[0]
    elif len(scope.region_ids) == 1 and not scope.node_ids and not scope.nationwide:
        args["region_id"] = scope.region_ids[0]
    _run_tool(deps, state, calls, evidence, facts, "orient", 0, "get_anomalies", args)
    for node_id in [*scope.node_ids, *scope.unknown_ids][:2]:
        _run_tool(
            deps, state, calls, evidence, facts, "orient", 0, "get_topology", {"node_id": node_id}
        )
    return {"calls": calls, "evidence": evidence, "facts": facts}


def investigate(state: AgentState, deps: Deps) -> dict[str, Any]:
    """One turn: the model writes a note and asks for tools; code runs them."""
    cfg = deps.config
    iteration = state.iteration + 1
    human = (
        render_case_file(state, cfg)
        + "\n\nFirst write your note as plain text, then call the tools you need next. "
        "If the evidence is sufficient, write your final note and call no tool."
    )
    result, step = _call_llm(
        deps, state, "investigate", f"investigate turn {iteration}",
        prompts.investigate_system(cfg.disabled_tools),
        human, tools=[t for t in tool_schemas() if t["name"] not in cfg.disabled_tools],
    )  # fmt: skip
    update: dict[str, Any] = {"steps": [*state.steps, step], "iteration": iteration}
    if result is None:
        update["investigating"] = False
        update["issues"] = [*state.issues, f"investigation stopped early: {step.error}"]
        emit(state, "error", where="investigate", message=step.error)
        return update

    notes = list(state.notes)
    text = result.text.strip()
    if text:
        notes.append(Note(iteration=iteration, text=text))
        emit(state, "note", iteration=iteration, text=text)

    requested = result.tool_calls
    room = max(0, cfg.max_tool_calls - state.tool_calls_used)
    allowed = requested[: min(cfg.max_calls_per_iteration, room)]
    if len(allowed) < len(requested):
        cut = len(requested) - len(allowed)
        why = "tool call budget used up" if room <= len(allowed) else "limit per turn"
        notes.append(
            Note(
                iteration=iteration,
                source="system",
                text=f"{cut} requested call(s) not run: {why}.",
            )
        )

    if not allowed:
        # The model wants to stop (or has no budget left).
        update["notes"] = notes
        missing = missing_checks(state)
        if cfg.completeness_gate and not state.gate_fired and missing and room > 0:
            msg = (
                f"Not yet checked for the affected scope and window: {', '.join(missing)}. "
                "Call the tools for them: a note is not a check."
            )
            notes.append(Note(iteration=iteration, source="gate", text=msg))
            update.update(gate_fired=True, investigating=True)
            emit(state, "gate", missing=missing, message=msg)
        else:
            update["investigating"] = False
        return update

    calls = list(state.calls)
    evidence = dict(state.evidence)
    facts = dict(state.facts)
    for call in allowed:
        _run_tool(
            deps, state, calls, evidence, facts, "investigate", iteration, call.name, call.args
        )
    used = state.tool_calls_used + len(allowed)
    update.update(
        notes=notes,
        calls=calls,
        evidence=evidence,
        facts=facts,
        tool_calls_used=used,
        investigating=iteration < cfg.max_iterations and used < cfg.max_tool_calls,
    )
    return update


def route_after_investigate(state: AgentState) -> str:
    return "investigate" if state.investigating else "conclude"


def conclude(state: AgentState, deps: Deps) -> dict[str, Any]:
    cfg = deps.config
    human = conclude_message(state, cfg) + "\n\nWrite the report now."
    budget = cfg.conclude_max_output_tokens
    result, step = _call_llm(
        deps, state, "conclude", "conclude", prompts.CONCLUDE_SYSTEM, human,
        schema=Report, max_output_tokens=budget,
    )  # fmt: skip
    steps = [*state.steps, step]
    raw = step.raw_output
    for attempt in range(1, cfg.conclude_retries + 1):
        if isinstance(getattr(result, "parsed", None), Report) or not _malformed(step):
            break
        result, step = _call_llm(
            deps, state, "conclude", f"conclude retry {attempt}", prompts.CONCLUDE_SYSTEM,
            human + prompts.CONCISE_SUFFIX, schema=Report, max_output_tokens=budget,
        )  # fmt: skip
        steps.append(step)
        raw = step.raw_output or raw
    update: dict[str, Any] = {"steps": steps}
    if result is not None and isinstance(result.parsed, Report):
        update["report"] = result.parsed
        return update
    reason = step.error or "no report was returned"
    partial = salvage_report(raw, _call_findings(state)[:MAX_FINDINGS]) if raw else None
    if partial is not None:
        update["report"] = partial
        update["issues"] = [*state.issues, PARTIAL_NOTE]
        emit(state, "error", where="conclude", message=PARTIAL_NOTE)
    else:
        update["report"] = fallback_report(reason, _call_findings(state))
        update["error"] = f"conclude failed: {reason}"
        emit(state, "error", where="conclude", message=reason)
    return update


def _malformed(step: LLMStep) -> bool:
    """The model answered, but not with a valid report (as opposed to not answering at all)."""
    return "MalformedOutput" in f"{step.error} {' '.join(step.attempts)}"


def _call_findings(state: AgentState) -> list[Finding]:
    return [
        Finding(claim=f"{c.tool}: {c.headline}"[:220], basis="observed", refs=[c.ref])
        for c in state.calls
        if not c.error and not c.duplicate_of
    ][:10]


def _tail(
    state: AgentState, deps: Deps, report: Report, problems: list[str]
) -> tuple[Report, list[str]]:
    """What verify does without a model: strip what stays invalid, cap confidence, check claims."""
    notes: list[str] = []
    if problems:
        notes += [f"unresolved: {p}" for p in problems]
        report, removed = strip_invalid(report, deps.reference, state.asked_at)
        notes += removed
    tool_of = {c.ref: c.tool for c in state.calls}
    report, capped = cap_confidence(report, state.evidence, tool_of, missing_checks(state))
    report, faithful = check_faithfulness(report, state.evidence, state.calls, deps.reference)
    return report, [*notes, *capped, *faithful]


def verify(state: AgentState, deps: Deps) -> dict[str, Any]:
    report = state.report
    assert report is not None and state.scope is not None
    cfg, issues = deps.config, list(state.issues)
    steps = list(state.steps)
    report, cut = limit_report(report)
    issues += cut
    checked = check_report(report, state.evidence, deps.reference, state.asked_at)
    report, problems = checked.report, checked.problems
    repairs = 0
    while problems and repairs < cfg.max_repairs and not state.error and not is_partial(issues):
        repairs += 1
        issues += [f"[repaired] {p}" for p in problems]
        human = conclude_message(state, cfg) + prompts.REPAIR_SUFFIX.format(
            problems="\n".join(f"- {p}" for p in problems), report=report.model_dump_json()
        )
        result, step = _call_llm(
            deps,
            state,
            "repair",
            f"repair {repairs}",
            prompts.CONCLUDE_SYSTEM,
            human,
            schema=Report,
            max_output_tokens=cfg.conclude_max_output_tokens,
        )
        steps.append(step)
        if result is None or not isinstance(result.parsed, Report):
            issues.append(f"repair call failed: {step.error}")
            break
        bounded, cut = limit_report(result.parsed)
        issues += cut
        checked = check_report(bounded, state.evidence, deps.reference, state.asked_at)
        report, problems = checked.report, checked.problems
    report, tail_notes = _tail(state, deps, report, problems)

    before_checks: Report | None = None
    if cfg.lookalike_checks and not state.error and not is_partial(issues):
        facts = Facts.from_rows(state.facts)

        def contradictions(candidate: Report) -> list[str]:
            return lookalike_problems(
                candidate, facts, deps.reference, state.asked_at, cfg.lookalike_checks
            )

        found = contradictions(report)
        if found:
            before_checks = report
        for attempt in range(1, cfg.max_lookalike_repairs + 1):
            if not found:
                break
            issues += [f"[lookalike] {p}" for p in found]
            human = conclude_message(state, cfg) + prompts.LOOKALIKE_SUFFIX.format(
                problems="\n".join(f"- {p}" for p in found), report=report.model_dump_json()
            )
            result, step = _call_llm(
                deps,
                state,
                "repair",
                f"lookalike repair {attempt}",
                prompts.CONCLUDE_SYSTEM,
                human,
                schema=Report,
                max_output_tokens=cfg.conclude_max_output_tokens,
            )
            steps.append(step)
            if result is None or not isinstance(result.parsed, Report):
                issues.append(f"lookalike repair call failed: {step.error}")
                break
            bounded, cut = limit_report(result.parsed)
            issues += cut
            checked = check_report(bounded, state.evidence, deps.reference, state.asked_at)
            report, tail_notes = _tail(state, deps, checked.report, checked.problems)
            found = contradictions(report)
        if found:
            report = report.model_copy(update={"confidence": "low"})
            tail_notes += [f"lookalike unresolved: {p}" for p in found]
            tail_notes.append(
                "Confidence set to low: the report still contradicts records the investigation "
                "fetched."
            )
    issues += tail_notes
    if state.error:
        issues.append(state.error)
    issues += deps.store_errors
    emit(state, "report", report=report.model_dump(mode="json"), issues=issues)
    update: dict[str, Any] = {"report": report, "issues": issues, "steps": steps}
    if before_checks is not None:
        update["report_before_checks"] = before_checks
    return update


def render(state: AgentState, deps: Deps) -> dict[str, Any]:
    assert state.report is not None
    return {"markdown": render_markdown(state.report, state.evidence, issues=state.issues)}


__all__ = ["Deps", "IntakeOutput", "missing_checks", "to_local"]
