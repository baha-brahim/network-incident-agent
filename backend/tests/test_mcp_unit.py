"""The MCP server, connected to an in-process client with a fake executor. No database."""

from datetime import UTC, datetime
from typing import Any

import pytest
from mcp import Client
from mcp.types import TextContent
from sqlalchemy import create_engine

from incident_agent.agent.tools import tool_schemas
from incident_agent.agent.types import ToolContext, ToolResult
from incident_agent.mcp_server import build_server
from incident_agent.mcp_server.server import instructions

ASKED_AT = datetime(2026, 9, 22, 7, 38, tzinfo=UTC)
MODES = ["auto", "legacy"]  # the in-process shortcut, and the initialize handshake real clients use


def context() -> ToolContext:
    return ToolContext(engine=create_engine("sqlite://"), asked_at=ASKED_AT)


class Recorder:
    """An executor that remembers what it was asked and answers with a canned result."""

    def __init__(self, error: str | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any], datetime]] = []
        self.error = error

    def __call__(self, name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        self.calls.append((name, args, ctx.asked_at))
        return ToolResult(
            tool=name,
            args=args,
            headline=f"{name}: 1 row",
            body="ALM-000001 critical LINK_LOS",
            error=self.error,
        )


@pytest.mark.parametrize("mode", MODES)
async def test_the_listed_tools_are_the_ones_the_agent_uses(mode: str) -> None:
    async with Client(build_server(context(), Recorder()), mode=mode) as client:
        listed = (await client.list_tools()).tools
    expected = tool_schemas()
    assert len(listed) == 9
    assert [t.name for t in listed] == [s["name"] for s in expected]
    assert [t.description for t in listed] == [s["description"] for s in expected]
    assert [t.input_schema for t in listed] == [s["parameters"] for s in expected]


@pytest.mark.parametrize("mode", MODES)
async def test_a_call_runs_the_executor_as_of_the_context_time(mode: str) -> None:
    executor = Recorder()
    args = {"start": "2026-09-22 06:00", "end": "2026-09-22 07:30"}
    async with Client(build_server(context(), executor), mode=mode) as client:
        result = await client.call_tool("get_alarms", args)

    assert executor.calls == [("get_alarms", args, ASKED_AT)]
    assert not result.is_error
    [content] = result.content
    assert isinstance(content, TextContent)
    assert content.text == "get_alarms: 1 row\n\nALM-000001 critical LINK_LOS"


@pytest.mark.parametrize("mode", MODES)
async def test_a_tool_error_comes_back_as_an_error_result(mode: str) -> None:
    async with Client(build_server(context(), Recorder(error="Invalid arguments")), mode=mode) as c:
        result = await c.call_tool("get_alarms", {})
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert "get_alarms: 1 row" in result.content[0].text


@pytest.mark.parametrize("mode", MODES)
async def test_an_unknown_tool_is_an_error_result_not_an_exception(mode: str) -> None:
    async with Client(build_server(context()), mode=mode) as client:
        unknown = await client.call_tool("drop_table", {"name": "alarms"})
        invalid = await client.call_tool("get_alarms", {"start": 12})
    for result in (unknown, invalid):
        assert result.is_error
        assert isinstance(result.content[0], TextContent)
    assert "Unknown tool 'drop_table'" in unknown.content[0].text  # type: ignore[union-attr]
    assert "Invalid arguments" in invalid.content[0].text  # type: ignore[union-attr]


def test_the_instructions_name_the_local_time_of_the_cutoff() -> None:
    text = instructions(context())
    assert "2026-09-22 08:38" in text and "Africa/Tunis" in text and "read-only" in text.lower()
    assert build_server(context()).instructions == text
