"""Serve the investigation tools over MCP on stdio.

uv run python -m incident_agent.mcp_server [--asked-at "2026-09-22 08:38"]

Stdout carries the protocol, so logs go to stderr.
"""

import argparse
import logging
import sys

import anyio
from mcp.server.stdio import stdio_server

from incident_agent.agent.tools.timeutil import TimeParseError, parse_time
from incident_agent.agent.types import ToolContext
from incident_agent.api.datasets import dataset_facts
from incident_agent.db.session import get_agent_engine
from incident_agent.mcp_server.server import build_server


async def serve(ctx: ToolContext) -> None:
    server = build_server(ctx)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m incident_agent.mcp_server", description=__doc__
    )
    parser.add_argument(
        "--asked-at",
        help="the tools' 'now', Africa/Tunis local time (default: the dataset's now)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)

    engine = get_agent_engine()
    try:
        asked_at = parse_time(args.asked_at) if args.asked_at else dataset_facts(engine).now
    except TimeParseError as exc:
        parser.error(str(exc))
    anyio.run(serve, ToolContext(engine=engine, asked_at=asked_at))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
