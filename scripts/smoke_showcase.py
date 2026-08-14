"""Exercise the deterministic web showcase and focused MCP surface."""
import asyncio
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from umich_transit.mcp_server.demo import build_demo_server
from umich_transit.web.demo import build_demo_app


async def _mcp_tool_names(database_url: str) -> set[str]:
    mcp, stack = build_demo_server(database_url)
    async with stack:
        return {tool.name for tool in await mcp.list_tools()}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="umich-transit-showcase-") as tmp:
        demo_path = Path(tmp) / "showcase-demo.db"
        app = build_demo_app(f"sqlite:///{demo_path}")
        with TestClient(app) as client:
            assert client.get("/api/health").json() == {"status": "ok"}
            assert client.get("/api/meta").json() == {"demo_mode": True}
            assert client.get("/api/accuracy").json()["status"] == "ready"
            assert client.get("/api/stops/search", params={"q": "central"}).json()[
                "stops"
            ]
            assert client.get("/").status_code == 200
            assert client.get("/static/app.js").status_code == 200

        mcp_path = Path(tmp) / "showcase-mcp-demo.db"
        names = asyncio.run(_mcp_tool_names(f"sqlite:///{mcp_path}"))
        assert "prediction_accuracy" in names
        assert "plan_trip" not in names
    print("Showcase smoke check passed: demo web + accuracy + MCP tools")


if __name__ == "__main__":
    main()
