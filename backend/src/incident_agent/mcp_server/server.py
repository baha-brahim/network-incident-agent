"""The MCP server: the registry's read-only tools, offered to any client as of a fixed "now"."""

from typing import Any

import anyio.to_thread
import mcp.types as types
from mcp.server import Server, ServerRequestContext

from incident_agent.agent.nodes import ToolExecutor
from incident_agent.agent.tools import execute_tool, tool_schemas
from incident_agent.agent.tools.timeutil import LOCAL_TZ_NAME, fmt
from incident_agent.agent.types import ToolContext, ToolResult

SERVER_NAME = "network-incident-agent"


def instructions(ctx: ToolContext) -> str:
    return (
        "Read-only tools over a synthetic mobile network: KPIs, detector alerts, topology, "
        "alarms, changes, maintenance, external events and runbooks. Every tool sees data only "
        f"up to {fmt(ctx.asked_at)} ({LOCAL_TZ_NAME} local time); nothing later exists for it. "
        "Cite the IDs (alerts, alarms, changes, nodes, runbook chunks) that appear in the output."
    )


def as_tool_result(result: ToolResult) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(text=f"{result.headline}\n\n{result.body}")],
        is_error=result.error is not None,
    )


def build_server(ctx: ToolContext, execute: ToolExecutor = execute_tool) -> Server[Any]:
    """A server whose tools are exactly the ones the agent uses, all run against `ctx`."""

    async def list_tools(
        _: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=schema["name"],
                    description=schema["description"],
                    input_schema=schema["parameters"],
                )
                for schema in tool_schemas()
            ]
        )

    async def call_tool(
        _: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        # Tools query the database synchronously; keep the protocol loop free meanwhile.
        result = await anyio.to_thread.run_sync(
            execute, params.name, dict(params.arguments or {}), ctx
        )
        return as_tool_result(result)

    return Server(
        SERVER_NAME,
        instructions=instructions(ctx),
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
