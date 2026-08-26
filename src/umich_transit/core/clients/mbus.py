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
import structlog

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


logger = structlog.get_logger(__name__)


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


def _eta_from_prd(raw: dict[str, Any], fallback_stop_id: str = "") -> EtaRecord:
    """Build an EtaRecord from one BusTime `prd` entry. When querying many stops
    each entry carries its own `stpid`; the single-stop path passes a fallback."""
    return EtaRecord(
        route_id=str(raw.get("rt") or ""),
        stop_id=str(raw.get("stpid") or fallback_stop_id),
        vehicle_id=str(raw.get("vid") or ""),
        predicted_arrival_at=_parse_ts(str(raw["prdtm"])),
        captured_at=_parse_ts(str(raw["tmstmp"])),
    )


class MbusClient:
    def __init__(self, *, base_url: str, api_key: str, http: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/") + API_PATH
        self._key = api_key
        self._http = http

    async def _get(self, endpoint: str, **params: str) -> Any:
        query = {"key": self._key, "format": "json", **params}
        resp = await self._http.get(self._base + endpoint, params=query)
        resp.raise_for_status()
        try:
            payload = resp.json()
        except ValueError as exc:
            snippet = resp.text[:200]
            raise BusTimeError(
                f"BusTime returned non-JSON response for {endpoint}: {snippet!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise BusTimeError(f"BusTime response for {endpoint} was not an object")
        if "bustime-response" not in payload:
            raise BusTimeError(f"BusTime response for {endpoint} was missing bustime-response")
        body = payload["bustime-response"]
        if not isinstance(body, dict):
            raise BusTimeError(f"BusTime response for {endpoint} had an invalid body")
        errors = body.get("error")
        if errors is not None:
            if isinstance(errors, dict):
                errors = [errors]
            elif not isinstance(errors, list):
                raise BusTimeError(f"BusTime response for {endpoint} had an invalid error field")
            if any(not isinstance(error, dict) for error in errors):
                raise BusTimeError(f"BusTime response for {endpoint} had an invalid error entry")
            msgs = [str(e.get("msg", "")) for e in errors]
            non_benign = [m for m in msgs if not m.startswith(_BENIGN_ERROR_PREFIXES)]
            if non_benign or not msgs:
                raise BusTimeError(
                    "; ".join(msgs) or "BusTime returned an empty error array"
                )
            # All errors are benign per-route/stop "no data" notes. BusTime can
            # still include real data alongside them (e.g. getvehicles across
            # several routes), so fall through and return the full body rather
            # than discarding it.
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
        skipped = 0
        for ptr in body.get("ptr", []):
            if not isinstance(ptr, dict):
                skipped += 1
                continue
            for pt in ptr.get("pt", []):
                if not isinstance(pt, dict):
                    skipped += 1
                    continue
                if pt.get("typ") != "S":
                    continue
                try:
                    out.append((int(pt["seq"]), StopRecord(
                        id=str(pt["stpid"]),
                        agency="mbus",
                        name=str(pt.get("stpnm") or pt["stpid"]),
                        lat=float(pt["lat"]),
                        lon=float(pt["lon"]),
                        raw=pt,
                    )))
                except (KeyError, ValueError, TypeError):
                    skipped += 1
        if skipped:
            logger.warning(
                "mbus.skipped_malformed_entries", endpoint="/getpatterns", skipped=skipped,
            )
        return out

    async def get_vehicle_positions(self, route_ids: list[str]) -> list[VehicleRecord]:
        """Vehicles for the given routes. BusTime getvehicles takes up to 10
        comma-separated route ids per call."""
        if not route_ids:
            return []
        out: list[VehicleRecord] = []
        skipped = 0
        for chunk in _chunked(route_ids, 10):
            body = await self._get("/getvehicles", rt=",".join(chunk))
            for raw in body.get("vehicle", []):
                if not isinstance(raw, dict):
                    skipped += 1
                    continue
                try:
                    hdg: Any = raw.get("hdg")
                    out.append(VehicleRecord(
                        id=str(raw["vid"]),
                        route_id=str(raw.get("rt") or ""),
                        lat=float(raw["lat"]),
                        lon=float(raw["lon"]),
                        heading=float(hdg) if hdg not in (None, "") else None,
                        captured_at=_parse_ts(str(raw["tmstmp"])),
                    ))
                except (KeyError, ValueError, TypeError):
                    skipped += 1
        if skipped:
            logger.warning(
                "mbus.skipped_malformed_entries", endpoint="/getvehicles", skipped=skipped,
            )
        return out

    async def get_etas(self, stop_id: str) -> list[EtaRecord]:
        """Upcoming arrival predictions for a single stop (BusTime getpredictions)."""
        body = await self._get("/getpredictions", stpid=stop_id)
        out: list[EtaRecord] = []
        skipped = 0
        for raw in body.get("prd", []):
            if not isinstance(raw, dict):
                skipped += 1
                continue
            try:
                out.append(_eta_from_prd(raw, stop_id))
            except (KeyError, ValueError, TypeError):
                skipped += 1
        if skipped:
            logger.warning(
                "mbus.skipped_malformed_entries", endpoint="/getpredictions", skipped=skipped,
            )
        return out

    async def get_etas_for_stops(self, stop_ids: list[str]) -> list[EtaRecord]:
        """Predictions for many stops in one sweep. BusTime getpredictions accepts
        up to 10 comma-separated stpid per call, so this issues ceil(N/10) requests
        instead of N — the main lever on daily API-quota usage."""
        out: list[EtaRecord] = []
        skipped = 0
        for chunk in _chunked(stop_ids, 10):
            body = await self._get("/getpredictions", stpid=",".join(chunk))
            for raw in body.get("prd", []):
                if not isinstance(raw, dict):
                    skipped += 1
                    continue
                try:
                    out.append(_eta_from_prd(raw))
                except (KeyError, ValueError, TypeError):
                    skipped += 1
        if skipped:
            logger.warning(
                "mbus.skipped_malformed_entries", endpoint="/getpredictions", skipped=skipped,
            )
        return out
