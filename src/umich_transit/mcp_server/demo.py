"""Deterministic MCP showcase entry point."""
import asyncio
from contextlib import AsyncExitStack

from mcp.server.fastmcp import FastMCP

from umich_transit.core.demo import build_demo_service
from umich_transit.mcp_server.server import build_server

DEMO_DATABASE_URL = "sqlite:///data/demo-transit-mcp.db"


def build_demo_server(
    database_url: str = DEMO_DATABASE_URL,
) -> tuple[FastMCP, AsyncExitStack]:
    """Build an MCP server backed by deterministic historical and live data."""
    service, engine = build_demo_service(database_url)
    mcp, stack = build_server(service)
    stack.callback(engine.dispose)
    return mcp, stack


async def _run() -> None:
    mcp, stack = build_demo_server()
    async with stack:
        await mcp.run_stdio_async()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
