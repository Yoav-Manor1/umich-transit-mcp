"""Runtime selection for local, demo, and deployed web applications."""

from typing import Literal, cast

import httpx
from fastapi import FastAPI

from umich_transit.config import Settings
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url
from umich_transit.demo.service import DemoTransitService
from umich_transit.web.protocols import WebTransitService

AppMode = Literal["local", "demo", "live"]


def resolve_app_mode(configured: str | None, *, on_vercel: bool) -> AppMode:
    """Validate the configured application mode.

    Local development preserves the historical default. Vercel deployments
    must opt into demo or live behavior explicitly so they cannot silently
    launch against ephemeral local storage.
    """
    if configured is None:
        if on_vercel:
            raise ValueError("TRANSIT_APP_MODE is required on Vercel")
        return "local"
    if configured not in {"local", "demo", "live"}:
        raise ValueError("TRANSIT_APP_MODE must be local, demo, or live")
    return cast(AppMode, configured)


def build_runtime_service(
    mode: AppMode,
    config: Settings,
) -> tuple[WebTransitService, httpx.AsyncClient | None]:
    """Construct the selected data service and any HTTP client it owns."""
    if mode == "demo":
        return DemoTransitService(), None

    api_key = config.mbus_api_key.get_secret_value().strip()
    if mode == "live":
        if not api_key:
            raise ValueError("MBUS_API_KEY is required in live mode")
        if not config.database_url.startswith(("postgres://", "postgresql://")):
            raise ValueError("Live mode requires a PostgreSQL DATABASE_URL")

    engine = create_engine_for_url(config.database_url)
    http = httpx.AsyncClient(timeout=15.0)
    mbus = MbusClient(
        base_url=config.mbus_base_url,
        api_key=api_key,
        http=http,
    )
    return cast(WebTransitService, TransitService(engine=engine, mbus=mbus)), http


def build_runtime_app(config: Settings | None = None) -> FastAPI:
    """Build the FastAPI application selected by environment configuration."""
    from umich_transit.web.app import build_app

    runtime_config = config or Settings()
    mode = resolve_app_mode(
        runtime_config.transit_app_mode,
        on_vercel=runtime_config.vercel,
    )
    service, http = build_runtime_service(mode, runtime_config)
    return build_app(
        service,
        app_mode=mode,
        managed_http=http,
    )
