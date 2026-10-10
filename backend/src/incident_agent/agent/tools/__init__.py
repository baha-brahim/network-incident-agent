"""Read-only investigation tools. Each is a pure function `(ToolContext, args) -> ToolResult`."""

from incident_agent.agent.tools.registry import (
    TOOLS,
    ToolSpec,
    execute_tool,
    tool_schemas,
)

__all__ = ["TOOLS", "ToolSpec", "execute_tool", "tool_schemas"]
