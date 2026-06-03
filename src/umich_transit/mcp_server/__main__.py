"""Entry point for the MCP server (stdio)."""
import asyncio

from umich_transit.mcp_server.server import build_server


async def _run() -> None:
    mcp, stack = build_server()
    async with stack:
        await mcp.run_stdio_async()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
