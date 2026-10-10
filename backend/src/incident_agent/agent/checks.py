"""Which look-alike checks (calendar, change log, external events) a run has actually made."""

from datetime import datetime

from incident_agent.agent.state import AgentState
from incident_agent.agent.tools.timeutil import TimeParseError, parse_time

# Tools whose absence from a run leaves the look-alike explanations unchecked.
LOOKALIKE_TOOLS = {
    "get_maintenance": "the maintenance calendar",
    "get_changes": "the change log",
    "get_external_events": "external events",
}


def _when(value: object) -> datetime | None:
    try:
        return parse_time(str(value))
    except TimeParseError:
        return None


def missing_checks(state: AgentState) -> list[str]:
    """Look-alike checks with no successful tool call covering the scope's window and region."""
    scope = state.scope
    done: set[str] = set()
    for call in state.calls:
        if call.tool not in LOOKALIKE_TOOLS or call.error or call.duplicate_of:
            continue
        if scope is not None:
            start, end = _when(call.args.get("start")), _when(call.args.get("end"))
            if (
                start is not None
                and end is not None
                and (end < scope.window_start or start > scope.window_end)
            ):
                continue
            region = call.args.get("region_id")
            if region and scope.region_ids and str(region).upper() not in scope.region_ids:
                continue
        done.add(call.tool)
    return [label for tool, label in LOOKALIKE_TOOLS.items() if tool not in done]
