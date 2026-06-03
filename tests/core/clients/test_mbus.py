"""Tests for the Magic Bus (Clever Devices BusTime v3) client. Uses respx."""
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx

from umich_transit.core.clients.mbus import BusTimeError, MbusClient, _parse_ts

FIXTURES = Path(__file__).parents[2] / "fixtures" / "mbus"
BASE = "https://mbus.example.test/bustime/api/v3"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as http:
        yield MbusClient(
            base_url="https://mbus.example.test",
            api_key="testkey",
            http=http,
        )


@respx.mock
async def test_get_routes_parses_fixture(client):
    respx.get(url__startswith=BASE + "/getroutes").mock(
        return_value=httpx.Response(200, text=_load("getroutes.json")))
    routes = await client.get_routes()
    assert [r.id for r in routes] == ["BB", "CN", "NW"]
    assert routes[0].long_name == "Bursley-Baits"
    assert routes[0].agency == "mbus"
    assert routes[0].color == "#00274c"


@respx.mock
async def test_get_pattern_stops_returns_only_stops_with_sequence(client):
    respx.get(url__startswith=BASE + "/getpatterns").mock(
        return_value=httpx.Response(200, text=_load("getpatterns_BB.json")))
    stops = await client.get_pattern_stops("BB")
    # Waypoint (typ="W") is excluded; only the two typ="S" stops remain.
    assert [(seq, s.id) for seq, s in stops] == [(1, "1001"), (3, "1002")]
    assert stops[0][1].name == "Bursley Hall"
    assert stops[0][1].lat == pytest.approx(42.27594)


@respx.mock
async def test_get_vehicle_positions_parses_fixture(client):
    respx.get(url__startswith=BASE + "/getvehicles").mock(
        return_value=httpx.Response(200, text=_load("getvehicles.json")))
    vehicles = await client.get_vehicle_positions(["BB"])
    assert len(vehicles) == 1
    v = vehicles[0]
    assert v.id == "5001"
    assert v.route_id == "BB"
    assert v.lat == pytest.approx(42.278)
    assert v.heading == pytest.approx(45.0)
    assert v.captured_at.tzinfo is not None  # localized


@respx.mock
async def test_get_vehicle_positions_empty_route_list_skips_call(client):
    vehicles = await client.get_vehicle_positions([])
    assert vehicles == []


@respx.mock
async def test_get_etas_parses_fixture(client):
    respx.get(url__startswith=BASE + "/getpredictions").mock(
        return_value=httpx.Response(200, text=_load("getpredictions.json")))
    etas = await client.get_etas(stop_id="1001")
    assert len(etas) == 1
    e = etas[0]
    assert e.route_id == "BB"
    assert e.stop_id == "1001"
    assert e.vehicle_id == "5001"
    assert isinstance(e.predicted_arrival_at, datetime)
    assert e.predicted_arrival_at.hour == 14
    assert e.predicted_arrival_at.minute == 35
    assert e.predicted_arrival_at.tzinfo is not None


@respx.mock
async def test_get_etas_no_arrivals_returns_empty(client):
    respx.get(url__startswith=BASE + "/getpredictions").mock(
        return_value=httpx.Response(200, text=_load("error_no_arrivals.json")))
    etas = await client.get_etas(stop_id="9999")
    assert etas == []


@respx.mock
async def test_invalid_or_missing_key_raises(client):
    respx.get(url__startswith=BASE + "/getroutes").mock(
        return_value=httpx.Response(200, text=_load("error_no_key.json")))
    with pytest.raises(BusTimeError):
        await client.get_routes()


@respx.mock
async def test_get_etas_raises_on_5xx(client):
    respx.get(url__startswith=BASE + "/getpredictions").mock(
        return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_etas(stop_id="1001")


def test_parse_ts_accepts_minute_and_second_formats():
    a = _parse_ts("20260602 14:35")
    b = _parse_ts("20260602 14:35:30")
    assert a.hour == 14 and a.minute == 35 and a.tzinfo is not None
    assert b.hour == 14 and b.minute == 35 and b.second == 30 and b.tzinfo is not None


@respx.mock
async def test_empty_error_array_raises(client):
    respx.get(url__startswith=BASE + "/getroutes").mock(
        return_value=httpx.Response(200, text='{"bustime-response": {"error": []}}'))
    with pytest.raises(BusTimeError):
        await client.get_routes()
