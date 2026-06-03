"""Validate your BusTime API key and inspect the live response shapes.

Run this AFTER setting MBUS_API_KEY in .env. It confirms your key works and
exercises the client parser against live data, so any field-mapping mismatch
shows up immediately (paste the output to get a fast fix).

    uv run python scripts/check_api.py
"""
import asyncio
import json

import httpx

from umich_transit.config import settings
from umich_transit.core.clients.mbus import MbusClient

BASE = settings.mbus_base_url.rstrip("/") + "/bustime/api/v3"


async def _raw(http: httpx.AsyncClient, key: str, endpoint: str, **params: str) -> dict:
    resp = await http.get(BASE + endpoint, params={"key": key, "format": "json", **params})
    return resp.json()


async def main() -> None:
    key = settings.mbus_api_key.get_secret_value()
    if not key:
        print("MBUS_API_KEY is empty - set it in .env first.")
        return

    async with httpx.AsyncClient(timeout=10.0) as http:
        gettime = await _raw(http, key, "/gettime")
        if "error" in gettime.get("bustime-response", {}):
            print("Key rejected:", gettime)
            return
        print("Key OK. Server time:", gettime["bustime-response"].get("tm"))

        print("\n--- raw getroutes (first 400 chars) ---")
        print(json.dumps(await _raw(http, key, "/getroutes"))[:400])

        client = MbusClient(base_url=settings.mbus_base_url, api_key=key, http=http)
        routes = await client.get_routes()
        print(f"\nParsed {len(routes)} routes.")
        if not routes:
            return
        rid = routes[0].id
        print("Sample route:", routes[0].model_dump(exclude={"raw"}))

        stops = await client.get_pattern_stops(rid)
        print(f"Parsed {len(stops)} pattern stops for route {rid}.")
        vehicles = await client.get_vehicle_positions([rid])
        print(f"Parsed {len(vehicles)} live vehicles on route {rid}.")

        if stops:
            sid = stops[0][1].id
            print(f"\n--- raw getpredictions for stop {sid} (first 400 chars) ---")
            print(json.dumps(await _raw(http, key, "/getpredictions", stpid=sid))[:400])
            etas = await client.get_etas(sid)
            print(f"\nParsed {len(etas)} predictions at stop {sid}.")

        print("\nAll good - the client parses live BusTime data correctly.")


if __name__ == "__main__":
    asyncio.run(main())
