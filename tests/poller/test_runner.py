"""Tests for the poller's DB-loader helpers (the testable, non-loop parts)."""
import asyncio
import json

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Base, Route, RouteStop, Stop
from umich_transit.poller.runner import (
    _load_detector_context,
    _load_route_ids,
    _load_stop_ids,
    _prediction_loop,
)


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with session_scope(eng) as s:
        s.add(Route(id="r1", agency="mbus", short_name="BB", long_name="Bursley-Baits"))
        s.add(Stop(id="s1", agency="mbus", name="A", lat=42.0, lon=-83.0))
        s.add(Stop(id="s2", agency="mbus", name="B", lat=42.1, lon=-83.1))
        s.add(RouteStop(route_id="r1", stop_id="s2", sequence=2))
        s.add(RouteStop(route_id="r1", stop_id="s1", sequence=1))
    return eng


def test_load_route_ids(engine):
    assert _load_route_ids(engine) == ["r1"]


def test_load_stop_ids(engine):
    assert sorted(_load_stop_ids(engine)) == ["s1", "s2"]


def test_load_detector_context_orders_stops_by_sequence(engine):
    stops, route_stops = _load_detector_context(engine)
    assert {s.id for s in stops} == {"s1", "s2"}
    # route_stops ordered by sequence -> s1 (seq 1) before s2 (seq 2)
    assert route_stops == {"r1": ["s1", "s2"]}


@respx.mock
async def test_prediction_error_log_never_contains_bus_time_key(engine, monkeypatch):
    sentinel = "SENTINEL-BUSTIME-KEY-9dfe"
    respx.get(url__startswith="https://mbus.example.test/bustime/api/v3").mock(
        return_value=httpx.Response(503)
    )

    async def stop_after_log(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop_after_log)
    async with httpx.AsyncClient() as http:
        client = MbusClient(
            base_url="https://mbus.example.test",
            api_key=sentinel,
            http=http,
        )
        with capture_logs() as logs, pytest.raises(asyncio.CancelledError):
            await _prediction_loop(engine, client)

    assert logs[-1]["event"] == "prediction_loop.error"
    assert sentinel not in json.dumps(logs)
