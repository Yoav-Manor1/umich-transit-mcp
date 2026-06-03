"""FastAPI app factory for the local bus dashboard.

Wiring mirrors mcp_server/server.py:build_server() — the same engine, httpx
client, MbusClient, and TransitService. Pass `svc` to inject a service in
tests; otherwise the lifespan builds one from settings and closes the HTTP
client on shutdown.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI, Request

from umich_transit.config import settings
from umich_transit.core.clients.mbus import BusTimeError, MbusClient
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url
from umich_transit.web.leave import compute_leave


def build_app(svc: TransitService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if getattr(app.state, "svc", None) is None:
            engine = create_engine_for_url(settings.database_url)
            http = httpx.AsyncClient(timeout=15.0)
            mbus = MbusClient(
                base_url=settings.mbus_base_url,
                api_key=settings.mbus_api_key.get_secret_value(),
                http=http,
            )
            app.state.svc = TransitService(engine=engine, mbus=mbus)
            app.state.http = http
        try:
            yield
        finally:
            http_client = getattr(app.state, "http", None)
            if http_client is not None:
                await http_client.aclose()

    app = FastAPI(title="U-Mich Transit Dashboard", lifespan=lifespan)
    app.state.svc = svc
    app.state.http = None

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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

    return app
