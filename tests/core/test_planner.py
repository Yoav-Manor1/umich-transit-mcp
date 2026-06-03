"""Tests for the same-route trip planner (v1: no transfers)."""
from datetime import UTC, datetime, timedelta

from umich_transit.core.planner import TripPlanner, TripSegment


def _arrival(now, mins_until, route_id, vehicle):
    return {
        "route_id": route_id, "stop_id": "s1", "vehicle_id": vehicle,
        "predicted_arrival_at": now + timedelta(minutes=mins_until),
        "adjusted_arrival_at": now + timedelta(minutes=mins_until + 1),
        "on_time_pct_at_this_hour": 0.7, "sample_size": 60, "confidence": "high",
    }


def test_no_plan_when_no_common_route():
    planner = TripPlanner(
        route_stops={"r1": ["s1", "s2"], "r2": ["s3", "s4"]},
        stop_to_routes={"s1": ["r1"], "s2": ["r1"], "s3": ["r2"], "s4": ["r2"]},
    )
    plan = planner.plan(from_stop_id="s1", to_stop_id="s3", upcoming_arrivals=[])
    assert plan is None


def test_picks_soonest_common_route():
    now = datetime.now(UTC)
    planner = TripPlanner(
        route_stops={"r1": ["s1", "s2"]},
        stop_to_routes={"s1": ["r1"], "s2": ["r1"]},
    )
    arrivals = [
        _arrival(now, 15, "r1", "v_late"),
        _arrival(now, 4, "r1", "v_soon"),
    ]
    plan = planner.plan(from_stop_id="s1", to_stop_id="s2", upcoming_arrivals=arrivals)
    assert plan is not None
    assert plan.segments[0].vehicle_id == "v_soon"
    assert isinstance(plan.segments[0], TripSegment)


def test_rejects_arrivals_for_wrong_route():
    now = datetime.now(UTC)
    planner = TripPlanner(
        route_stops={"r1": ["s1", "s2"], "r2": ["s1", "s9"]},
        stop_to_routes={"s1": ["r1", "r2"], "s2": ["r1"], "s9": ["r2"]},
    )
    arrivals = [
        _arrival(now, 2, "r2", "vx"),   # wrong route (r2 doesn't reach s2)
        _arrival(now, 8, "r1", "vy"),   # correct
    ]
    plan = planner.plan(from_stop_id="s1", to_stop_id="s2", upcoming_arrivals=arrivals)
    assert plan is not None
    assert plan.segments[0].vehicle_id == "vy"
