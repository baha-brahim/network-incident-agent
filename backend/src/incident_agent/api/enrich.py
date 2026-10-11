"""Details the agent keeps to itself, added to the events the web interface receives.

The agent's `tool_result` event has only a headline. A `ToolRecorder` wraps the agent's tool
executor, keeps every result, and the stream hands them back in call order.
"""

import json
import logging
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from incident_agent.agent.nodes import ToolExecutor
from incident_agent.agent.types import EvidenceRef, ToolContext, ToolResult
from incident_agent.api.jsonsafe import cap_data, to_jsonable

log = logging.getLogger(__name__)

MAX_REFS = 60
MAX_SUMMARY = 300
ChartFn = Callable[[ToolContext, ToolResult], list[dict[str, Any]] | None]
_DUPLICATE = re.compile(r"^Identical to (T\d+);")


def _key(name: str, args: dict[str, Any]) -> str:
    return json.dumps([name, args], sort_keys=True, default=str)


@dataclass
class Recorded:
    name: str
    args: dict[str, Any]  # as the agent passed them
    result: ToolResult
    chart: list[dict[str, Any]] | None = None


class ToolRecorder:
    """A tool executor that remembers what it returned. Safe to call from the agent's threads."""

    def __init__(self, execute: ToolExecutor, charts: ChartFn | None = None) -> None:
        self._execute = execute
        self._charts = charts
        self._recorded: deque[Recorded] = deque()

    def __call__(self, name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        result = self._execute(name, args, ctx)
        chart = None
        if self._charts is not None and name == "query_kpis" and not result.error:
            try:
                chart = self._charts(ctx, result)
            except Exception:  # a chart is an extra: never fail the tool call for it
                log.exception("chart for query_kpis failed")
        self._recorded.append(Recorded(name, dict(args), result, chart))
        return result

    def take(self, name: str, args: dict[str, Any]) -> Recorded | None:
        """The next recorded call, if it is the one `name` and `args` describe.

        Calls the agent skips because they repeat an earlier one were never executed, so they are
        not in the queue; a head that does not match means the event is such a repeat.
        """
        if self._recorded and _key(self._recorded[0].name, self._recorded[0].args) == _key(
            name, args
        ):
            return self._recorded.popleft()
        return None


def evidence_items(refs: list[EvidenceRef]) -> list[dict[str, Any]]:
    return [
        {"ref": r.ref, "kind": r.kind, "summary": r.summary[:MAX_SUMMARY]} for r in refs[:MAX_REFS]
    ]


def tool_result_extras(
    recorded: Recorded | None, call_args: dict[str, Any], headline: str
) -> dict[str, Any]:
    """The fields added to a `tool_result`: args, body, refs, data (and why there may be none)."""
    if recorded is not None:
        result = recorded.result
        data, cut = cap_data(result.data)
        if recorded.chart:
            data = {**(data if isinstance(data, dict) else {}), "chart": recorded.chart}
        return {
            "args": to_jsonable(result.args if isinstance(result.args, dict) else call_args),
            "body": result.body,
            "refs": evidence_items(result.refs),
            "data": data,
            "data_truncated": cut,
            "duplicate_of": None,
        }
    repeat = _DUPLICATE.match(headline)
    return {
        "args": to_jsonable(call_args),
        "body": f"Identical to {repeat.group(1)}; not run again." if repeat else headline,
        "refs": [],
        "data": None,
        "data_truncated": False,
        "duplicate_of": repeat.group(1) if repeat else None,
    }


def evidence_map(evidence: dict[str, EvidenceRef]) -> dict[str, dict[str, str]]:
    return {
        ref: {"kind": item.kind, "summary": item.summary[:MAX_SUMMARY]}
        for ref, item in evidence.items()
    }
