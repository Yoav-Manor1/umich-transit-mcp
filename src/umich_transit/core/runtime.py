"""Live service construction shared by web and MCP entry points."""
from dataclasses import dataclass

import httpx

from umich_transit.config import settings
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url


@dataclass(frozen=True)
class LiveServiceResources:
    service: TransitService
    http: httpx.AsyncClient


def build_live_service() -> LiveServiceResources:
    engine = create_engine_for_url(settings.database_url)
    http = httpx.AsyncClient(timeout=15.0)
    mbus = MbusClient(
        base_url=settings.mbus_base_url,
        api_key=settings.mbus_api_key.get_secret_value(),
        http=http,
    )
    return LiveServiceResources(
        service=TransitService(engine=engine, mbus=mbus),
        http=http,
    )
