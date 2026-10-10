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
        "Alerts and anomalies raised by the anomaly detector that overlap a time window, with "
        "the metrics that moved and by how much. Alerts still running at the current time are "
        "described only up to now.",
        GetAnomaliesArgs,
        get_anomalies,
    ),
    ToolSpec(
        "query_kpis",
        "KPI series for cells, sites, regions, the whole network or core nodes, compared with a "
        "baseline from earlier days at the same time of day. Reports the mean, extremes, the "
        "onset and recovery time of any deviation, steps with no data, and a short series.",
        QueryKpisArgs,
        query_kpis,
    ),
    ToolSpec(
        "get_topology",
        "Dependency chain of a node up to the core, the nodes below it, its siblings under the "
        "same parent, and its attributes (area type, link medium, venue). Use it to see what a "
        "link or router failure would take down.",
        GetTopologyArgs,
        get_topology,
    ),
    ToolSpec(
        "get_alarms",
        "Alarms in a time window, sorted by time with raised/cleared/active state, for nodes "
        "(and the nodes below them) or a region. Alarms not yet cleared at the current time "
        "are shown as active.",
        GetAlarmsArgs,
        get_alarms,
    ),
    ToolSpec(
        "get_changes",
        "Change records (config pushes, upgrades, tuning, rollbacks) executed in a window on "
        "given nodes and their parents. Shows which changes were rolled back and which change "
        "a rollback reverts.",
        GetChangesArgs,
        get_changes,
    ),
    ToolSpec(
        "get_maintenance",
        "Maintenance windows overlapping a range on given nodes and their parents, with "
        "description, expected impact and state (completed, in progress, planned). Planned "
        "windows later than the current time are shown.",
        GetMaintenanceArgs,
        get_maintenance,
    ),
    ToolSpec(
        "get_external_events",
        "External events (stadium events, public holidays, festivals) overlapping a window, "
        "including nationwide ones.",
        GetExternalEventsArgs,
        get_external_events,
    ),
    ToolSpec(
        "search_runbooks",
        "Search the operations runbooks for diagnosis procedures, differential diagnosis and "
        "alarm meanings. Returns excerpts with chunk ids to cite.",
        SearchRunbooksArgs,
        search_runbooks_tool,
    ),
    ToolSpec(
        "run_sql",
        "Last resort, when no other tool fits: one read-only SELECT over cell_kpis, core_kpis, "
        "alarms, changes, maintenance, external_events, nodes, cells and regions (bare table "
        "names; rows after the current time are hidden; at most 50 rows). Times in literals "
        "are Africa/Tunis local.",
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
