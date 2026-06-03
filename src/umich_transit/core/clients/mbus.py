"""Magic Bus client for the Clever Devices BusTime API v3.

Magic Bus (mbus.ltp.umich.edu) exposes BusTime under /bustime/api/v3. All
requests require an API key and use format=json; responses are wrapped in
{"bustime-response": {...}}. Timestamps are agency-local (America/Detroit) with
no timezone, so we localize them; the storage layer converts to UTC on write.
"""
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from umich_transit.core.clients.base import (
    EtaRecord,
    RouteRecord,
    StopRecord,
    VehicleRecord,
)

API_PATH = "/bustime/api/v3"
AGENCY_TZ = ZoneInfo("America/Detroit")

# BusTime returns HTTP 200 with an "error" array even for "no results" cases.
# These message prefixes mean "no data", not a real failure — treat as empty.
_BENIGN_ERROR_PREFIXES = (
    "No arrival times",
    "No service scheduled",
    "No data found for parameter",
)


class BusTimeError(RuntimeError):
    """A non-benign error returned by the BusTime API (e.g. bad/missing key)."""


def _parse_ts(value: str) -> datetime:
    """Parse a BusTime local timestamp into an America/Detroit-aware datetime.

    BusTime emits 'YYYYMMDD HH:MM' for predictions/vehicles and 'YYYYMMDD
    HH:MM:SS' for other endpoints, so both are accepted. NOTE: during the
    one-hour DST fall-back window these naive local times are ambiguous; we
    resolve to fold=0 (the earlier, EDT occurrence), which can make a timestamp
    in that window up to 1h early. This is an accepted limitation of BusTime's
    naive-timestamp protocol — it cannot be disambiguated from the string alone.
    """
    for fmt in ("%Y%m%d %H:%M:%S", "%Y%m%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=AGENCY_TZ)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized BusTime timestamp: {value!r}")


def _chunked(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class MbusClient:
    def __init__(self, *, base_url: str, api_key: str, http: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/") + API_PATH
        self._key = api_key
        self._http = http

    async def _get(self, endpoint: str, **params: str) -> Any:
        query = {"key": self._key, "format": "json", **params}
        resp = await self._http.get(self._base + endpoint, params=query)
        resp.raise_for_status()
        body = resp.json().get("bustime-response", {})
        if "error" in body:
            msgs = [str(e.get("msg", "")) for e in body["error"]]
            if msgs and all(m.startswith(_BENIGN_ERROR_PREFIXES) for m in msgs):
                return {}
            raise BusTimeError("; ".join(msgs) or "BusTime returned an empty error array")
        return body

    async def get_routes(self) -> list[RouteRecord]:
        body = await self._get("/getroutes")
        out: list[RouteRecord] = []
        for raw in body.get("routes", []):
            out.append(RouteRecord(
                id=str(raw["rt"]),
                agency="mbus",
                short_name=str(raw.get("rtdd") or raw["rt"]),
                long_name=str(raw.get("rtnm") or raw["rt"]),
                color=raw.get("rtclr"),
                raw=raw,
            ))
        return out

    async def get_pattern_stops(self, route_id: str) -> list[tuple[int, StopRecord]]:
        """Return (sequence, StopRecord) for each stop (typ=='S') on the route's
        pattern(s). Waypoints (typ=='W') are skipped."""
        body = await self._get("/getpatterns", rt=route_id)
        out: list[tuple[int, StopRecord]] = []
        for ptr in body.get("ptr", []):
            for pt in ptr.get("pt", []):
                if pt.get("typ") != "S":
                    continue
                out.append((int(pt["seq"]), StopRecord(
                    id=str(pt["stpid"]),
                    agency="mbus",
                    name=str(pt.get("stpnm") or pt["stpid"]),
                    lat=float(pt["lat"]),
                    lon=float(pt["lon"]),
                    raw=pt,
                )))
        return out

    async def get_vehicle_positions(self, route_ids: list[str]) -> list[VehicleRecord]:
        """Vehicles for the given routes. BusTime getvehicles takes up to 10
        comma-separated route ids per call."""
        if not route_ids:
            return []
        out: list[VehicleRecord] = []
        for chunk in _chunked(route_ids, 10):
            body = await self._get("/getvehicles", rt=",".join(chunk))
            for raw in body.get("vehicle", []):
                hdg = raw.get("hdg")
                out.append(VehicleRecord(
                    id=str(raw["vid"]),
                    route_id=str(raw.get("rt") or ""),
                    lat=float(raw["lat"]),
                    lon=float(raw["lon"]),
                    heading=float(hdg) if hdg not in (None, "") else None,
                    captured_at=_parse_ts(str(raw["tmstmp"])),
                ))
        return out

    async def get_etas(self, stop_id: str) -> list[EtaRecord]:
        """Upcoming arrival predictions for a stop (BusTime getpredictions)."""
        body = await self._get("/getpredictions", stpid=stop_id)
        out: list[EtaRecord] = []
        for raw in body.get("prd", []):
            out.append(EtaRecord(
                route_id=str(raw.get("rt") or ""),
                stop_id=str(raw.get("stpid") or stop_id),
                vehicle_id=str(raw.get("vid") or ""),
                predicted_arrival_at=_parse_ts(str(raw["prdtm"])),
                captured_at=_parse_ts(str(raw["tmstmp"])),
            ))
        return out
