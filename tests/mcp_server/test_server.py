"""Tests for the public MCP tool surface."""
import asyncio

from umich_transit.mcp_server.demo import build_demo_server
from umich_transit.mcp_server.server import build_server


def test_showcase_registers_accuracy_and_retires_incomplete_trip_planner():
    async def tool_names() -> set[str]:
        mcp, stack = build_server()
        async with stack:
            return {tool.name for tool in await mcp.list_tools()}

    names = asyncio.run(tool_names())

    assert "prediction_accuracy" in names
    assert "plan_trip" not in names


def test_demo_mcp_server_uses_the_same_showcase_surface(tmp_path):
    async def tool_names() -> set[str]:
        database_url = f"sqlite:///{tmp_path / 'showcase-demo.db'}"
        mcp, stack = build_demo_server(database_url)
        async with stack:
            return {tool.name for tool in await mcp.list_tools()}

    names = asyncio.run(tool_names())

    assert names == {
        "find_stops",
        "get_arrivals",
        "list_routes",
        "prediction_accuracy",
        "route_reliability",
    }
