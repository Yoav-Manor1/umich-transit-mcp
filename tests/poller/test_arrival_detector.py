"""Tests for the hysteresis-based arrival detector.

The detector is a stateful object fed a stream of vehicle observations; it
emits DetectedArrival events. We exercise it with synthetic GPS trails.
"""
from datetime import UTC, datetime, timedelta

from umich_transit.core.clients.base import StopRecord, VehicleRecord
from umich_transit.poller.arrival_detector import (
    ArrivalDetector,
    DetectedArrival,
)


def _stops() -> list[StopRecord]:
    # Two stops ~200m apart along an east-west axis
    return [
        StopRecord(id="s1", agency="mbus", name="A",
                   lat=42.0000, lon=-83.0000, raw={}),
        StopRecord(id="s2", agency="mbus", name="B",
                   lat=42.0000, lon=-82.99760, raw={}),  # ~200m east
    ]


def _vehicle(at: datetime, lat: float, lon: float) -> VehicleRecord:
    return VehicleRecord(id="v1", route_id="r1", lat=lat, lon=lon, captured_at=at)


def _route_stops_for_route():
    return {"r1": ["s1", "s2"]}


def test_no_arrival_when_far_away():
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50,
    )
    t = datetime.now(UTC)
    events = detector.observe(_vehicle(t, 42.001, -83.001))  # ~145m from s1
    assert events == []


def test_arrival_emitted_on_entering_threshold():
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50,
    )
    t = datetime.now(UTC)
    # Step 1: approaching, not yet within 30m
    detector.observe(_vehicle(t, 42.0000, -83.0005))  # ~41m from s1
    # Step 2: now within 30m
    events = detector.observe(_vehicle(t + timedelta(seconds=15),
                                       42.0000, -83.00020))  # ~16m
    assert len(events) == 1
    assert events[0].stop_id == "s1"
    assert events[0].vehicle_id == "v1"


def test_no_duplicate_arrival_while_still_at_stop():
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50,
    )
    t = datetime.now(UTC)
    detector.observe(_vehicle(t, 42.0000, -83.00020))           # within 30m
    detector.observe(_vehicle(t + timedelta(seconds=10),
                              42.0000, -83.00018))               # still within
    events = detector.observe(_vehicle(t + timedelta(seconds=20),
                                       42.0000, -83.00015))      # still within
    # Only the first observation should have emitted an arrival
    assert events == []


def test_re_arrival_allowed_after_departure():
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50,
    )
    t = datetime.now(UTC)
    detector.observe(_vehicle(t, 42.0000, -83.00020))            # arrive s1
    detector.observe(_vehicle(t + timedelta(seconds=10),
                              42.0000, -83.0010))                 # depart (>50m)
    events = detector.observe(_vehicle(t + timedelta(seconds=30),
                                       42.0000, -83.00020))       # re-arrive s1
    assert len(events) == 1


def test_gps_jitter_does_not_cause_duplicates():
    # Hysteresis: bouncing between ~16m and ~33m should not produce two arrivals.
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50,
    )
    t = datetime.now(UTC)
    detector.observe(_vehicle(t, 42.0000, -83.00020))            # ~16m: ARRIVE
    detector.observe(_vehicle(t + timedelta(seconds=5),
                              42.0000, -83.00040))  # ~33m: still AT (between enter and exit)
    events = detector.observe(_vehicle(t + timedelta(seconds=10),
                                       42.0000, -83.00020))        # ~16m: still AT
    assert events == []


def test_state_times_out_after_long_silence():
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50, stale_after_seconds=600,
    )
    t = datetime.now(UTC)
    detector.observe(_vehicle(t, 42.0000, -83.00020))   # arrive s1
    # Long gap, then a re-arrival at s1 — should fire because state was dropped
    events = detector.observe(_vehicle(t + timedelta(minutes=20),
                                       42.0000, -83.00020))
    assert len(events) == 1


def test_arrival_record_carries_route_and_timestamp():
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50,
    )
    t = datetime.now(UTC)
    events = detector.observe(_vehicle(t, 42.0000, -83.00020))
    a: DetectedArrival = events[0]
    assert a.route_id == "r1"
    assert a.actual_arrival_at == t
    assert a.detected_via == "proximity"
