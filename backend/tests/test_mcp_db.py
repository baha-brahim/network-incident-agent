"""The MCP server with the real tools, on the fixture world."""

from collections.abc import Iterator

import pytest
from mcp import Client
from mcp.types import TextContent
from sqlalchemy import Engine

from incident_agent.agent.types import ToolContext
from incident_agent.mcp_server import build_server
from tests.fixtures_world import NOW
from tests.test_agent_db import setup_world

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def world(db_engine: Engine) -> Iterator[Engine]:
    yield from setup_world(db_engine)


async def test_the_real_tools_answer_through_the_server(
    world: Engine, agent_ro_engine: Engine
) -> None:
    server = build_server(ToolContext(engine=agent_ro_engine, asked_at=NOW))
    async with Client(server) as client:
        result = await client.call_tool("get_topology", {"node_id": "S-TUN-001"})
    assert not result.is_error
    assert isinstance(result.content[0], TextContent)
    assert "S-TUN-001" in result.content[0].text and "LNK-TUN-01-A" in result.content[0].text
