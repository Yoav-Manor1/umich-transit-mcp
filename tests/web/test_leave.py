"""Unit tests for the when-to-leave computation."""
from datetime import UTC, datetime, timedelta

from umich_transit.web.leave import compute_leave

NOW = datetime(2026, 6, 3, 17, 0, tzinfo=UTC)


def _eta(minutes, route="CN", confidence="low", adj_minutes=None):
    pred = NOW + timedelta(minutes=minutes)
    adj = NOW + timedelta(minutes=adj_minutes) if adj_minutes is not None else pred
    return {
        "route_id": route,
        "predicted_arrival_at": pred,
        "adjusted_arrival_at": adj,
        "confidence": confidence,
    }


def test_returns_none_when_no_arrivals():
    assert compute_leave([], walk_min=5, now=NOW) is None


def test_counts_down_when_walk_less_than_eta():
    res = compute_leave([_eta(10)], walk_min=4, now=NOW)
    assert res is not None
    assert res["leave_in_min"] == 6
    assert res["route_id"] == "CN"


def test_leave_now_when_walk_exceeds_eta():
    res = compute_leave([_eta(3)], walk_min=5, now=NOW)
    assert res is not None
    assert res["leave_in_min"] == 0


def test_picks_soonest_bus():
    res = compute_leave([_eta(12, route="CS"), _eta(6, route="CN")], walk_min=2, now=NOW)
    assert res is not None
    assert res["route_id"] == "CN"
    assert res["leave_in_min"] == 4


def test_uses_adjusted_eta_when_high_confidence():
    # published 6 min, but history says 12; high confidence -> plan for 12
    res = compute_leave(
        [_eta(6, confidence="high", adj_minutes=12)], walk_min=2, now=NOW
    )
    assert res is not None
    assert res["leave_in_min"] == 10


def test_uses_adjusted_eta_when_medium_confidence():
    res = compute_leave(
        [_eta(6, confidence="medium", adj_minutes=10)], walk_min=2, now=NOW
    )
    assert res is not None
    assert res["leave_in_min"] == 8
