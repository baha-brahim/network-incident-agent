"""The case file: the only thing a model sees besides its system prompt.

Old tool output is reduced to its headline; only the newest results that fit the budget are shown in
full. The model's own notes carry what it learned from the older ones.
"""

from incident_agent.agent.checks import missing_checks
from incident_agent.agent.config import AgentConfig
from incident_agent.agent.state import AgentState, CallRecord, Note
from incident_agent.agent.tools.timeutil import fmt, to_local
from incident_agent.agent.types import EvidenceRef

HEADLINE_CHARS = 220
SHORT_HEADLINE_CHARS = 110
ARG_CHARS = 90

KIND_ORDER = ["alert", "alarm", "change", "maintenance", "event", "runbook", "anomaly", "node"]


def _cut(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def format_args(args: dict[str, object]) -> str:
    parts = []
    for key, value in args.items():
        if value is None or value == [] or value == "":
            continue
        shown = ",".join(map(str, value)) if isinstance(value, list) else str(value)
        parts.append(f"{key}={_cut(shown, ARG_CHARS)}")
    return ", ".join(parts)


def call_line(call: CallRecord, headline_chars: int = HEADLINE_CHARS) -> str:
    head = _cut(call.headline, headline_chars)
    return f"{call.ref} {call.tool}({format_args(call.args)}) -> {head}"


def _body_block(call: CallRecord, headline_chars: int) -> str:
    """A result in full, minus its first line when the log line above already shows it whole."""
    body = call.body
    first, _, rest = body.partition("\n")
    headline = " ".join(call.headline.split())
    if " ".join(first.split()) == headline and len(headline) <= headline_chars:
        body = rest
    return f"--- {call.ref} {call.tool}\n{body}" if body else ""


def _header(state: AgentState, config: AgentConfig) -> list[str]:
    now = to_local(state.asked_at)
    lines = [
        "CASE FILE",
        f"Question: {state.question}",
        f"Now: {fmt(state.asked_at)} ({now.strftime('%A')}, Africa/Tunis). "
        "Data after this time does not exist.",
    ]
    scope = state.scope
    if scope is not None:
        where = []
        if scope.nationwide:
            where.append("nationwide")
        if scope.region_ids:
            where.append("regions " + ", ".join(scope.region_ids))
        if scope.node_ids:
            where.append("nodes " + ", ".join(scope.node_ids))
        lines.append(
            f"Scope: {scope.symptom}. Window {fmt(scope.window_start)} to {fmt(scope.window_end)}"
            + (" (ongoing)" if scope.ongoing else "")
            + f". {'; '.join(where) or 'No place named'}."
            + (
                " The window is a default: the question gave none."
                if scope.source == "default"
                else ""
            )
        )
    lines.append(
        f"Budget: turn {min(state.iteration + 1, config.max_iterations)} of "
        f"{config.max_iterations}; {state.tool_calls_used} of {config.max_tool_calls} "
        "tool calls used."
    )
    return lines


def _note_text(note: Note, limit: int) -> str:
    label = note.source if note.source != "model" else f"turn {note.iteration}"
    return f"[{label}] {_cut(note.text, limit)}"


def _notes_section(notes: list[Note], config: AgentConfig, budget: int) -> list[str]:
    """The newest notes that fit `budget`; the newest one is always kept (cut if needed)."""
    chosen: list[str] = []
    used = 0
    for note in reversed(notes):
        line = _note_text(note, config.note_chars)
        if chosen and used + len(line) + 1 > budget:
            break
        if not chosen and len(line) > budget:
            line = line[:budget].rstrip() + "..."
        chosen.append(line)
        used += len(line) + 1
    dropped = len(notes) - len(chosen)
    lines = list(reversed(chosen))
    if dropped:
        lines.insert(0, f"({dropped} older note(s) not shown)")
    return lines


def render_case_file(state: AgentState, config: AgentConfig) -> str:
    """Render the case file. Never longer than `config.casefile_chars`."""
    budget = config.casefile_chars
    header = _header(state, config)
    fixed = sum(len(x) + 1 for x in header)

    log_budget = int(budget * 0.35)
    headline_chars = HEADLINE_CHARS
    log = [call_line(c, headline_chars) for c in state.calls]
    if sum(len(x) + 1 for x in log) > log_budget:
        headline_chars = SHORT_HEADLINE_CHARS
        log = [call_line(c, headline_chars) for c in state.calls]
    log_len = sum(len(x) + 1 for x in log) + 40

    notes = _notes_section(state.notes, config, int(budget * 0.3)) if state.notes else []
    notes_len = sum(len(x) + 1 for x in notes) + 20

    room = budget - fixed - log_len - notes_len - 120
    bodies: list[str] = []
    for call in reversed(state.calls):
        if call.duplicate_of:
            continue
        block = _body_block(call, headline_chars)
        if not block:
            continue
        if len(block) + 1 > room:
            break
        bodies.append(block)
        room -= len(block) + 1
    bodies.reverse()

    lines = [*header, "", "TOOL CALLS"]
    lines += log or ["(none yet)"]
    if bodies:
        lines += [
            "",
            "LATEST RESULTS (each continues its log line; older ones are only the log line)",
        ]
        lines += bodies
    if notes:
        lines += ["", "YOUR NOTES SO FAR", *notes]
    text = "\n".join(lines)
    return text if len(text) <= budget else text[: budget - 4].rstrip() + " ..."


def render_registry(state: AgentState, config: AgentConfig) -> str:
    """Citable references other than call refs, as 'ref: summary', most useful kinds first."""
    rows = [e for e in state.evidence.values() if e.kind != "call"]
    rows.sort(key=lambda e: KIND_ORDER.index(e.kind) if e.kind in KIND_ORDER else len(KIND_ORDER))
    lines: list[str] = []
    used = 0
    for ref in rows:
        line = f"{ref.ref}: {_cut(ref.summary, 130)}"
        if used + len(line) + 1 > config.registry_chars:
            break
        lines.append(line)
        used += len(line) + 1
    left = len(rows) - len(lines)
    if left:
        lines.append(f"(+{left} more ids appear in the tool results above and may be cited)")
    return "\n".join(lines)


def conclude_message(state: AgentState, config: AgentConfig) -> str:
    """Case file plus the list of citable references; together within `casefile_chars`."""
    registry = render_registry(state, config)
    smaller = config.model_copy(
        update={"casefile_chars": max(2_000, config.casefile_chars - len(registry) - 120)}
    )
    parts = [render_case_file(state, smaller)]
    if registry:
        parts += ["", "CITABLE REFERENCES (T1, T2, ... are the tool calls above)", registry]
    missing = missing_checks(state)
    if missing:
        parts += ["", f"NOT CHECKED (no tool call made): {', '.join(missing)}."]
    return "\n".join(parts)


def evidence_kinds(evidence: dict[str, EvidenceRef], refs: list[str]) -> set[str]:
    return {evidence[r].kind for r in refs if r in evidence}
