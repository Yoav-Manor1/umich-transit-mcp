"""FastAPI app factory for the local bus dashboard.

Wiring mirrors mcp_server/server.py:build_server() — the same engine, httpx
client, MbusClient, and TransitService. Pass `svc` to inject a service in
tests; otherwise the lifespan builds one from settings and closes the HTTP
client on shutdown.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from umich_transit.config import settings
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url


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

    return app
