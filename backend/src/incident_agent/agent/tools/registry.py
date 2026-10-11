"""The tool registry: what the model is told about each tool, and a never-raising executor."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from incident_agent.agent.tools.alarms import GetAlarmsArgs, get_alarms
from incident_agent.agent.tools.anomalies import GetAnomaliesArgs, get_anomalies
from incident_agent.agent.tools.changes import GetChangesArgs, get_changes
from incident_agent.agent.tools.common import error_result, trim
from incident_agent.agent.tools.events import GetExternalEventsArgs, get_external_events
from incident_agent.agent.tools.kpis import QueryKpisArgs, query_kpis
from incident_agent.agent.tools.maintenance import GetMaintenanceArgs, get_maintenance
from incident_agent.agent.tools.run_sql import RunSqlArgs, run_sql
from incident_agent.agent.tools.runbooks import SearchRunbooksArgs, search_runbooks_tool
from incident_agent.agent.tools.schema import json_schema
from incident_agent.agent.tools.topology import GetTopologyArgs, get_topology
from incident_agent.agent.types import ToolContext, ToolResult


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str  # part of the prompt: keep it short and exact
    args_model: type[BaseModel]
    func: Callable[[ToolContext, Any], ToolResult]


_SPECS = [
    ToolSpec(
        "get_anomalies",
        "Detector alerts overlapping a window.",
        GetAnomaliesArgs,
        get_anomalies,
    ),
    ToolSpec(
        "query_kpis",
        "KPI series vs a time-of-day baseline, with onset and recovery.",
        QueryKpisArgs,
        query_kpis,
    ),
    ToolSpec(
        "get_topology",
        "Parents, children, siblings and attributes of a node.",
        GetTopologyArgs,
        get_topology,
    ),
    ToolSpec(
        "get_alarms",
        "Alarms in a window for nodes (and children) or a region.",
        GetAlarmsArgs,
        get_alarms,
    ),
    ToolSpec(
        "get_changes",
        "Changes and rollbacks in a window on nodes and their parents.",
        GetChangesArgs,
        get_changes,
    ),
    ToolSpec(
        "get_maintenance",
        "Maintenance windows, past to planned, on nodes and parents.",
        GetMaintenanceArgs,
        get_maintenance,
    ),
    ToolSpec(
        "get_external_events",
        "External events (stadium, holiday, festival) in a window.",
        GetExternalEventsArgs,
        get_external_events,
    ),
    ToolSpec(
        "search_runbooks",
        "Search runbooks for diagnosis procedures and alarm meanings.",
        SearchRunbooksArgs,
        search_runbooks_tool,
    ),
    ToolSpec(
        "run_sql",
        "Last resort: one read-only SELECT over cell_kpis, core_kpis, alarms, changes, "
        "maintenance, external_events, nodes, cells, regions.",
        RunSqlArgs,
        run_sql,
    ),
]

TOOLS: dict[str, ToolSpec] = {spec.name: spec for spec in _SPECS}


def tool_schemas() -> list[dict[str, Any]]:
    """Tool definitions to bind to a chat model: name, description and a plain JSON schema."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": json_schema(spec.args_model),
        }
        for spec in TOOLS.values()
    ]


def _validation_message(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]) or "arguments"
        parts.append(f"{where}: {err['msg']}")
    return trim("Invalid arguments - " + "; ".join(parts), 400)


def execute_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Run a tool. Never raises: bad names, bad arguments and database errors become errors."""
    spec = TOOLS.get(name)
    if spec is None:
        return error_result(
            name,
            args if isinstance(args, dict) else {},
            f"Unknown tool {name!r}. Tools: {', '.join(TOOLS)}.",
        )
    safe_args = args if isinstance(args, dict) else {}
    try:
        parsed = spec.args_model.model_validate(safe_args)
    except ValidationError as exc:
        return error_result(name, safe_args, _validation_message(exc))
    try:
        return spec.func(ctx, parsed)
    except Exception as exc:  # a tool must never take the investigation down
        return error_result(
            name, parsed, f"{name} failed: {type(exc).__name__}: {trim(str(exc), 300)}"
        )
