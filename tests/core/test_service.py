"""Tests for the service layer shared by MCP tools and a future HTTP API."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from umich_transit.core.clients.base import EtaRecord
from umich_transit.core.reliability import BinKey
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Base, ReliabilityStat, Route, Stop


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with session_scope(eng) as s:
        s.add(Route(id="r1", agency="mbus", short_name="BB", long_name="Bursley-Baits"))
        s.add(Stop(id="s1", agency="mbus", name="Mason Hall", lat=42.27, lon=-83.74))
        s.add(Stop(id="s2", agency="mbus", name="Pierpont", lat=42.29, lon=-83.72))
    return eng


async def test_get_arrivals_adjusts_with_reliability_stat(engine):
    now = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)  # fixed instant for determinism
    key = BinKey.from_timestamp(route_id="r1", stop_id="s1", at=now)
    with session_scope(engine) as s:
        s.add(ReliabilityStat(
            route_id="r1", stop_id="s1", dow=key.dow, hour=key.hour,
            on_time_pct=0.8, mean_delay_s=180,
            p50_delay_s=120, p90_delay_s=400, sample_count=60,
            updated_at=now,
        ))
    fake_client = AsyncMock()
    fake_client.get_etas = AsyncMock(return_value=[
        EtaRecord(route_id="r1", stop_id="s1", vehicle_id="v1",
                  predicted_arrival_at=now + timedelta(seconds=60), captured_at=now),
    ])
    svc = TransitService(engine=engine, mbus=fake_client)
    arrivals = await svc.get_arrivals(stop_id="s1", now=now)
    assert len(arrivals) == 1
    a = arrivals[0]
    assert a["confidence"] == "high"
    assert a["adjusted_arrival_at"] == a["predicted_arrival_at"] + timedelta(seconds=180)
    assert a["sample_size"] == 60


async def test_get_arrivals_low_confidence_when_no_stat(engine):
    now = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
    fake_client = AsyncMock()
    fake_client.get_etas = AsyncMock(return_value=[
        EtaRecord(route_id="r1", stop_id="s1", vehicle_id="v1",
                  predicted_arrival_at=now + timedelta(seconds=60), captured_at=now),
    ])
    svc = TransitService(engine=engine, mbus=fake_client)
    arrivals = await svc.get_arrivals(stop_id="s1", now=now)
    assert arrivals[0]["confidence"] == "low"
    assert arrivals[0]["adjusted_arrival_at"] == arrivals[0]["predicted_arrival_at"]
    assert arrivals[0]["sample_size"] == 0


async def test_get_arrivals_filters_by_route(engine):
    now = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
    fake_client = AsyncMock()
    fake_client.get_etas = AsyncMock(return_value=[
        EtaRecord(route_id="r1", stop_id="s1", vehicle_id="v1",
                  predicted_arrival_at=now + timedelta(seconds=60), captured_at=now),
        EtaRecord(route_id="r2", stop_id="s1", vehicle_id="v2",
                  predicted_arrival_at=now + timedelta(seconds=120), captured_at=now),
    ])
    svc = TransitService(engine=engine, mbus=fake_client)
    arrivals = await svc.get_arrivals(stop_id="s1", route_id="r1", now=now)
    assert [a["route_id"] for a in arrivals] == ["r1"]


def test_list_routes_returns_dicts(engine):
    svc = TransitService(engine=engine, mbus=AsyncMock())
    rows = svc.list_routes()
    assert rows == [{
        "id": "r1", "agency": "mbus",
        "short_name": "BB", "long_name": "Bursley-Baits", "color": None,
    }]


def test_find_stops_returns_dicts(engine):
    svc = TransitService(engine=engine, mbus=AsyncMock())
    rows = svc.find_stops(query="mason")
    assert rows == [{
        "id": "s1", "agency": "mbus", "name": "Mason Hall",
        "lat": 42.27, "lon": -83.74,
    }]


def test_route_reliability_aggregates_weighted(engine):
    now = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
    with session_scope(engine) as s:
        s.add(ReliabilityStat(route_id="r1", stop_id="s1", dow=1, hour=8,
                              on_time_pct=0.8, mean_delay_s=100,
                              p50_delay_s=80, p90_delay_s=200, sample_count=10,
                              updated_at=now))
        s.add(ReliabilityStat(route_id="r1", stop_id="s2", dow=1, hour=8,
                              on_time_pct=0.6, mean_delay_s=200,
                              p50_delay_s=150, p90_delay_s=400, sample_count=30,
                              updated_at=now))
    svc = TransitService(engine=engine, mbus=AsyncMock())
    r = svc.route_reliability(route_id="r1")
    assert r["sample_count"] == 40
    # weighted mean delay = (100*10 + 200*30)/40 = 175
    assert r["mean_delay_s"] == pytest.approx(175.0)


def test_route_reliability_no_data(engine):
    svc = TransitService(engine=engine, mbus=AsyncMock())
    r = svc.route_reliability(route_id="ghost")
    assert r["sample_count"] == 0
