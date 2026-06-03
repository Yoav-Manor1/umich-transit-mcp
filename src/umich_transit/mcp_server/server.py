"""Build and configure the MCP server (stdio transport)."""
from contextlib import AsyncExitStack
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from umich_transit.config import settings
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url
from umich_transit.mcp_server import tools


def build_server() -> tuple[FastMCP, AsyncExitStack]:
    """Construct the MCP server and an AsyncExitStack the caller must enter at
    startup and exit at shutdown (closes the shared httpx client)."""
    mcp: FastMCP = FastMCP("umich-transit")
    stack = AsyncExitStack()

    engine = create_engine_for_url(settings.database_url)
    http = httpx.AsyncClient(timeout=15.0)
    mbus = MbusClient(
        base_url=settings.mbus_base_url,
        api_key=settings.mbus_api_key.get_secret_value(),
        http=http,
    )
    svc = TransitService(engine=engine, mbus=mbus)

    @mcp.tool()
    def list_routes(agency: str | None = None) -> dict[str, Any]:
        """List bus routes. agency='mbus' for U-M campus buses, 'theride' for AAATA."""
        return tools.list_routes_tool(svc, agency=agency)

    @mcp.tool()
    def find_stops(
        query: str = "",
        near: list[float] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Find bus stops by name; optionally sort by distance to [lat, lon]."""
        return tools.find_stops_tool(svc, query=query, near=near, limit=limit)

    @mcp.tool()
    async def get_arrivals(
        stop_id: str,
        route_id: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Upcoming arrivals at a stop with published AND reliability-adjusted ETAs."""
        return await tools.get_arrivals_tool(svc, stop_id=stop_id, route_id=route_id, limit=limit)

    @mcp.tool()
    def route_reliability(
        route_id: str,
        day_of_week: int | None = None,
        hour: int | None = None,
    ) -> dict[str, Any]:
        """Reliability stats for a route: on-time %, mean delay, sample count."""
        return tools.route_reliability_tool(
            svc, route_id=route_id, day_of_week=day_of_week, hour=hour
        )

    async def _close_http() -> None:
        await http.aclose()

    stack.push_async_callback(_close_http)

    return mcp, stack
