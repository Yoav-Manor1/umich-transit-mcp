"""FastAPI app factory for the local bus dashboard.

Wiring mirrors mcp_server/server.py:build_server() — the same engine, httpx
client, MbusClient, and TransitService. Pass `svc` to inject a service in
tests; otherwise the lifespan builds one from settings and closes the HTTP
client on shutdown.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from umich_transit.core.clients.mbus import BusTimeError
from umich_transit.core.runtime import build_live_service
from umich_transit.core.service import TransitService
from umich_transit.web.leave import compute_leave

STATIC_DIR = Path(__file__).resolve().parent / "static"


def build_app(svc: TransitService | None = None, *, demo_mode: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if getattr(app.state, "svc", None) is None:
            resources = build_live_service()
            app.state.svc = resources.service
            app.state.http = resources.http
        try:
            yield
        finally:
            http_client = getattr(app.state, "http", None)
            if http_client is not None:
                await http_client.aclose()

    app = FastAPI(title="U-Mich Transit Dashboard", lifespan=lifespan)
    app.state.svc = svc
    app.state.http = None
    app.state.demo_mode = demo_mode

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/meta")
    def meta(request: Request) -> dict[str, bool]:
        return {"demo_mode": bool(request.app.state.demo_mode)}

    @app.get("/api/stops/search")
    def search_stops(request: Request, q: str = "", limit: int = 8) -> dict[str, Any]:
        svc: TransitService = request.app.state.svc
        return {"stops": svc.find_stops(query=q, limit=limit)}

    @app.get("/api/arrivals")
    async def arrivals(
        request: Request, stop_id: str, walk_min: int = 5, limit: int = 5
    ) -> dict[str, Any]:
        svc: TransitService = request.app.state.svc
        now = datetime.now(UTC)
        try:
            items = await svc.get_arrivals(stop_id=stop_id, limit=limit)
        except (httpx.HTTPError, BusTimeError):
            return {
                "stop_id": stop_id, "now": now.isoformat(),
                "arrivals": [], "leave": None, "error": "upstream",
            }
        return {
            "stop_id": stop_id,
            "now": now.isoformat(),
            "arrivals": items,
            "leave": compute_leave(items, walk_min, now),
        }

    @app.get("/api/accuracy")
    def accuracy(request: Request) -> dict[str, Any]:
        svc: TransitService = request.app.state.svc
        return svc.prediction_accuracy()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
