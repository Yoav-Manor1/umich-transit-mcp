"""One-time backfill: pull routes + stops + route_stops from Magic Bus.

Idempotent. Requires a valid BusTime API key in MBUS_API_KEY.

Usage:
    uv run python scripts/seed_static_data.py
"""
import asyncio

import httpx

from umich_transit.config import settings
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.storage.db import create_engine_for_url
from umich_transit.core.storage.seed import seed_static_data


async def main() -> None:
    engine = create_engine_for_url(settings.database_url)
    async with httpx.AsyncClient(timeout=15.0) as http:
        client = MbusClient(
            base_url=settings.mbus_base_url,
            api_key=settings.mbus_api_key.get_secret_value(),
            http=http,
        )
        n_routes, n_stops, n_links = await seed_static_data(engine, client)
    print(f"Seeded {n_routes} routes, {n_stops} stops, {n_links} route-stop links.")


if __name__ == "__main__":
    asyncio.run(main())
