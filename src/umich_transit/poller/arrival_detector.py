"""Hysteresis-based arrival detector.

State machine per (vehicle_id, stop_id):
    APPROACHING -> AT_STOP   when distance < enter_meters
    AT_STOP     -> (cleared)  when distance > exit_meters

Only the APPROACHING -> AT_STOP transition emits a DetectedArrival.
After `stale_after_seconds` of no updates, per-vehicle state is dropped so a
later re-observation can fire again.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from umich_transit.core.clients.base import StopRecord, VehicleRecord
from umich_transit.core.geo import haversine_m


class _State(StrEnum):
    APPROACHING = "approaching"
    AT_STOP = "at_stop"


@dataclass(frozen=True)
class DetectedArrival:
    vehicle_id: str
    route_id: str
    stop_id: str
    actual_arrival_at: datetime
    detected_via: str = "proximity"


@dataclass
class _VehicleState:
    last_seen: datetime
    # stop_id -> AT_STOP while the vehicle remains within the exit threshold
    at_stops: dict[str, _State] = field(default_factory=dict)

class ArrivalDetector:
    def __init__(
        self,
        *,
        stops: list[StopRecord],
        route_stops: dict[str, list[str]],
        enter_meters: float,
        exit_meters: float,
        stale_after_seconds: int = 600,
    ) -> None:
        if exit_meters <= enter_meters:
            raise ValueError("exit_meters must be greater than enter_meters")
        self._stops_by_id = {s.id: s for s in stops}
        self._route_stops = route_stops
        self._enter = enter_meters
        self._exit = exit_meters
        self._stale = timedelta(seconds=stale_after_seconds)
        self._vehicles: dict[str, _VehicleState] = {}

    def observe(self, vehicle: VehicleRecord) -> list[DetectedArrival]:
        self._prune_stale(vehicle.captured_at)

        relevant_stop_ids = self._route_stops.get(vehicle.route_id, [])
        vstate = self._vehicles.get(vehicle.id)
        if vstate is None:
            vstate = _VehicleState(last_seen=vehicle.captured_at)
            self._vehicles[vehicle.id] = vstate
        vstate.last_seen = vehicle.captured_at

        events: list[DetectedArrival] = []
        for stop_id in relevant_stop_ids:
            stop = self._stops_by_id.get(stop_id)
            if stop is None:
                continue
            dist = haversine_m(vehicle.lat, vehicle.lon, stop.lat, stop.lon)
            current = vstate.at_stops.get(stop_id, _State.APPROACHING)

            if current is _State.APPROACHING and dist < self._enter:
                vstate.at_stops[stop_id] = _State.AT_STOP
                events.append(DetectedArrival(
                    vehicle_id=vehicle.id,
                    route_id=vehicle.route_id,
                    stop_id=stop_id,
                    actual_arrival_at=vehicle.captured_at,
                ))
            elif current is _State.AT_STOP and dist > self._exit:
                vstate.at_stops.pop(stop_id, None)
            # Otherwise stay in the current state (hysteresis band).
        return events

    def _prune_stale(self, now: datetime) -> None:
        stale = [vid for vid, vs in self._vehicles.items()
                 if now - vs.last_seen > self._stale]
        for vid in stale:
            self._vehicles.pop(vid, None)
