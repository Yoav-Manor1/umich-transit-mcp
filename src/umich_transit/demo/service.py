"""Database-free service backed by versioned, illustrative showcase data."""

import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

DEFAULT_FIXTURE = Path(__file__).parent / "fixtures" / "showcase.json"


class DemoTransitService:
    """Serve deterministic transit examples without network or database I/O."""

    def __init__(
        self,
        fixture_path: Path | None = None,
        now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        path = fixture_path or DEFAULT_FIXTURE
        self._fixture: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if self._fixture.get("version") != 1:
            raise ValueError("Unsupported demo fixture version")
        required = {"routes", "stops", "arrivals", "accuracy"}
        missing = required - self._fixture.keys()
        if missing:
            raise ValueError(f"Demo fixture missing keys: {sorted(missing)}")
        self._now = now_factory

    def list_routes(self, agency: str | None = None) -> list[dict[str, Any]]:
        routes = self._fixture["routes"]
        if agency is not None:
            routes = [route for route in routes if route["agency"] == agency]
        return deepcopy(routes)

    def find_stops(
        self,
        query: str = "",
        near: tuple[float, float] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        del near
        normalized = query.casefold()
        stops = [
            stop
            for stop in self._fixture["stops"]
            if normalized in stop["name"].casefold()
        ]
        stops.sort(key=lambda stop: stop["name"])
        return deepcopy(stops[:limit])

    async def get_arrivals(
        self,
        *,
        stop_id: str,
        route_id: str | None = None,
        limit: int = 5,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        moment = now or self._now()
        rows = [
            row
            for row in self._fixture["arrivals"]
            if row["stop_id"] == stop_id
            and (route_id is None or row["route_id"] == route_id)
        ]
        rows.sort(key=lambda row: row["published_offset_min"])
        arrivals: list[dict[str, Any]] = []
        for row in rows[:limit]:
            published = moment + timedelta(minutes=row["published_offset_min"])
            adjusted = moment + timedelta(minutes=row["adjusted_offset_min"])
            arrivals.append(
                {
                    "route_id": row["route_id"],
                    "stop_id": row["stop_id"],
                    "vehicle_id": row["vehicle_id"],
                    "predicted_arrival_at": published,
                    "adjusted_arrival_at": adjusted,
                    "on_time_pct_at_this_hour": row["on_time_pct"],
                    "sample_size": row["sample_size"],
                    "confidence": row["confidence"],
                    "adjustment_seconds": int((adjusted - published).total_seconds()),
                    "adjustment_reason": row["adjustment_reason"],
                    "aggregation_scope": row["aggregation_scope"],
                    "data_source": "demo",
                    "observation": {
                        "status": "demo",
                        "observed_at": moment,
                        "age_seconds": 0,
                    },
                    "evidence": {
                        "status": "illustrative",
                        "sample_size": row["sample_size"],
                        "aggregation_scope": row["aggregation_scope"],
                    },
                }
            )
        return arrivals

    def prediction_accuracy(self, route_id: str | None = None) -> dict[str, Any]:
        report = deepcopy(self._fixture["accuracy"])
        if route_id is not None:
            report["routes"] = [
                route for route in report["routes"] if route["route_id"] == route_id
            ]
        return cast(dict[str, Any], report)

    def readiness(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "mode": "demo",
            "data_source": "versioned_fixture",
            "fixture_version": self._fixture["version"],
        }
