"""Same-route trip planner.

Given upcoming arrivals at `from_stop_id` and the route->stops mapping, returns
the soonest single-route trip to `to_stop_id`, or None if no shared route. V1
does not support transfers.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TripSegment:
    mode: str  # "bus"
    route_id: str
    vehicle_id: str
    from_stop_id: str
    to_stop_id: str
    board_at: datetime
    adjusted_arrival_at: datetime


@dataclass(frozen=True)
class TripPlan:
    segments: list[TripSegment]


class TripPlanner:
    def __init__(
        self,
        *,
        route_stops: dict[str, list[str]],
        stop_to_routes: dict[str, list[str]],
    ) -> None:
        self._route_stops = route_stops
        self._stop_to_routes = stop_to_routes

    def plan(
        self,
        *,
        from_stop_id: str,
        to_stop_id: str,
        upcoming_arrivals: list[dict[str, Any]],
    ) -> TripPlan | None:
        common = set(self._stop_to_routes.get(from_stop_id, [])) & set(
            self._stop_to_routes.get(to_stop_id, [])
        )
        if not common:
            return None
        candidates = [a for a in upcoming_arrivals if a["route_id"] in common]
        if not candidates:
            return None
        candidates.sort(key=lambda a: a["adjusted_arrival_at"])
        chosen = candidates[0]
        seg = TripSegment(
            mode="bus",
            route_id=chosen["route_id"],
            vehicle_id=chosen["vehicle_id"],
            from_stop_id=from_stop_id,
            to_stop_id=to_stop_id,
            board_at=chosen["adjusted_arrival_at"],
            # V1 approximation: destination arrival time = board time. Real
            # in-vehicle travel time is deferred to v2 (needs schedule data).
            adjusted_arrival_at=chosen["adjusted_arrival_at"],
        )
        return TripPlan(segments=[seg])
