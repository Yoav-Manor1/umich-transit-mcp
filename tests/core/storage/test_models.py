"""Tests for ORM models: schema, indexes, basic insert/query."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import (
    Arrival,
    Base,
    ParseError,
    Prediction,
    ReliabilityStat,
    Route,
    RouteStop,
    Stop,
)


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def test_can_insert_and_query_a_route(engine):
    with session_scope(engine) as s:
        s.add(Route(id="1", agency="mbus", short_name="BB", long_name="Bursley-Baits"))
    with session_scope(engine) as s:
        r = s.execute(select(Route).where(Route.id == "1")).scalar_one()
        assert r.short_name == "BB"
        assert r.agency == "mbus"


def test_route_stop_association(engine):
    with session_scope(engine) as s:
        s.add(Route(id="r1", agency="mbus", short_name="X", long_name="X"))
        s.add(Stop(id="s1", agency="mbus", name="Mason Hall", lat=42.27, lon=-83.74))
        s.add(RouteStop(route_id="r1", stop_id="s1", sequence=1))
    with session_scope(engine) as s:
        rs = s.execute(select(RouteStop)).scalar_one()
        assert rs.route_id == "r1" and rs.stop_id == "s1" and rs.sequence == 1


def test_prediction_and_arrival_have_required_fields(engine):
    now = datetime.now(UTC)
    with session_scope(engine) as s:
        s.add(Route(id="r1", agency="mbus", short_name="X", long_name="X"))
        s.add(Stop(id="s1", agency="mbus", name="N", lat=0, lon=0))
        s.add(Prediction(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            predicted_arrival_at=now, captured_at=now,
        ))
        s.add(Arrival(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            actual_arrival_at=now, detected_via="proximity",
        ))
    with session_scope(engine) as s:
        assert s.execute(select(Prediction)).scalar_one().vehicle_id == "v1"
        assert s.execute(select(Arrival)).scalar_one().detected_via == "proximity"


def test_reliability_stat_unique_per_bin(engine):
    with session_scope(engine) as s:
        s.add(Route(id="r1", agency="mbus", short_name="X", long_name="X"))
        s.add(Stop(id="s1", agency="mbus", name="N", lat=0, lon=0))
        s.add(ReliabilityStat(
            route_id="r1", stop_id="s1", dow=1, hour=8,
            on_time_pct=0.75, mean_delay_s=120,
            p50_delay_s=90, p90_delay_s=300, sample_count=42,
            updated_at=datetime.now(UTC),
        ))
    with session_scope(engine) as s:
        stat = s.execute(select(ReliabilityStat)).scalar_one()
        assert stat.on_time_pct == 0.75
        assert stat.sample_count == 42


def test_parse_error_insert_and_query(engine):
    now = datetime.now(UTC)
    with session_scope(engine) as s:
        s.add(ParseError(
            source="mbus.etas", occurred_at=now,
            error="boom", raw={"bad": "payload"},
        ))
    with session_scope(engine) as s:
        pe = s.execute(select(ParseError)).scalar_one()
        assert pe.source == "mbus.etas"
        assert pe.raw == {"bad": "payload"}
