"""Tests for read-only query helpers used by the MCP service layer."""
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from umich_transit.core.storage import queries
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import (
    Arrival,
    Base,
    Prediction,
    ReliabilityStat,
    Route,
    Stop,
)


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with session_scope(eng) as s:
        s.add(Route(id="r1", agency="mbus", short_name="BB", long_name="Bursley-Baits"))
        s.add(Route(id="r2", agency="theride", short_name="4", long_name="Washtenaw"))
        s.add(Stop(id="s1", agency="mbus", name="Mason Hall", lat=42.27, lon=-83.74))
        s.add(Stop(id="s2", agency="mbus", name="Pierpont Commons", lat=42.29, lon=-83.72))
    return eng


def test_list_routes_filters_by_agency(engine):
    with session_scope(engine) as s:
        all_routes = queries.list_routes(s)
        mbus = queries.list_routes(s, agency="mbus")
        assert len(all_routes) == 2
        assert [r.id for r in mbus] == ["r1"]


def test_find_stops_does_substring_match(engine):
    with session_scope(engine) as s:
        hits = queries.find_stops(s, query="mason")
        assert [h.id for h in hits] == ["s1"]


def test_find_stops_can_sort_by_distance(engine):
    # Point closer to s2 than s1
    near = (42.291, -83.721)
    with session_scope(engine) as s:
        hits = queries.find_stops(s, query="", near=near, limit=2)
        assert [h.id for h in hits] == ["s2", "s1"]


def test_get_reliability_stat_returns_none_when_missing(engine):
    with session_scope(engine) as s:
        result = queries.get_reliability_stat(s, route_id="r1", stop_id="s1", dow=0, hour=8)
        assert result is None


def test_get_reliability_stat_returns_row(engine):
    with session_scope(engine) as s:
        s.add(ReliabilityStat(
            route_id="r1", stop_id="s1", dow=0, hour=8,
            on_time_pct=0.8, mean_delay_s=120,
            p50_delay_s=60, p90_delay_s=300, sample_count=50,
            updated_at=datetime.now(UTC),
        ))
    with session_scope(engine) as s:
        result = queries.get_reliability_stat(s, route_id="r1", stop_id="s1", dow=0, hour=8)
        assert result is not None
        assert result.sample_count == 50


def test_arrivals_in_window(engine):
    now = datetime.now(UTC)
    with session_scope(engine) as s:
        s.add(Arrival(route_id="r1", stop_id="s1", vehicle_id="v1",
                      actual_arrival_at=now - timedelta(days=1),
                      detected_via="proximity"))
        s.add(Arrival(route_id="r1", stop_id="s1", vehicle_id="v1",
                      actual_arrival_at=now - timedelta(days=100),
                      detected_via="proximity"))
    with session_scope(engine) as s:
        recent = queries.arrivals_in_window(
            s, route_id="r1", stop_id="s1",
            since=now - timedelta(days=90), until=now,
        )
        assert len(recent) == 1


def test_prediction_before_arrival(engine):
    now = datetime.now(UTC)
    with session_scope(engine) as s:
        s.add(Prediction(route_id="r1", stop_id="s1", vehicle_id="v1",
                         predicted_arrival_at=now + timedelta(minutes=1),
                         captured_at=now - timedelta(seconds=305)))
        s.add(Prediction(route_id="r1", stop_id="s1", vehicle_id="v1",
                         predicted_arrival_at=now + timedelta(minutes=1),
                         captured_at=now - timedelta(seconds=10)))
    with session_scope(engine) as s:
        match = queries.prediction_for_arrival(
            s, vehicle_id="v1", stop_id="s1",
            arrival_at=now, lookback_seconds=300,
        )
        # Should pick the prediction captured ~5 min before arrival
        assert match is not None
        # The 305-sec-old one is outside the lookback; the 10-sec-old one is inside.
        assert (now - match.captured_at).total_seconds() == pytest.approx(10, abs=1)


def test_prediction_for_arrival_returns_none_when_no_match(engine):
    now = datetime.now(UTC)
    with session_scope(engine) as s:
        match = queries.prediction_for_arrival(
            s, vehicle_id="ghost", stop_id="s1",
            arrival_at=now, lookback_seconds=300,
        )
        assert match is None


def test_find_stops_escapes_like_wildcards(engine):
    # A literal underscore should match no real stop name (none contain "_"),
    # proving "_" is not treated as a single-char wildcard.
    with session_scope(engine) as s:
        hits = queries.find_stops(s, query="_")
        assert hits == []


def test_tzdatetime_converts_aware_non_utc_to_utc(engine):
    eastern = timezone(timedelta(hours=-5))
    # 07:00 Eastern == 12:00 UTC, same instant
    t = datetime(2024, 1, 15, 7, 0, 0, tzinfo=eastern)
    with session_scope(engine) as s:
        s.add(Arrival(route_id="r1", stop_id="s1", vehicle_id="v1",
                      actual_arrival_at=t, detected_via="proximity"))
    with session_scope(engine) as s:
        got = s.execute(select(Arrival)).scalar_one().actual_arrival_at
        assert got == t                       # same instant preserved
        assert got.utcoffset() == timedelta(0)  # returned as UTC
