"""Tests for the web dashboard HTTP endpoints."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from umich_transit.core.clients.base import EtaRecord
from umich_transit.core.clients.mbus import BusTimeError
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Base, Route, Stop
from umich_transit.web.app import build_app


def _service(etas=None, raise_upstream=False):
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with session_scope(engine) as s:
        s.add(Route(id="CN", agency="mbus", short_name="CN", long_name="Commuter North"))
        s.add(Stop(id="C251", agency="mbus",
                   name="Central Campus Transit Center", lat=42.27, lon=-83.73))
    mbus = AsyncMock()
    if raise_upstream:
        mbus.get_etas = AsyncMock(side_effect=BusTimeError("bad key"))
    else:
        mbus.get_etas = AsyncMock(return_value=etas or [])
    return TransitService(engine=engine, mbus=mbus)


def test_health_ok():
    client = TestClient(build_app(_service()))
    assert client.get("/api/health").json() == {"status": "ok"}


def test_health_reports_application_mode_when_supplied():
    client = TestClient(build_app(_service(), app_mode="demo"))
    assert client.get("/api/health").json() == {"status": "ok", "mode": "demo"}


def test_search_returns_matching_stops():
    client = TestClient(build_app(_service()))
    r = client.get("/api/stops/search", params={"q": "central"})
    assert r.status_code == 200
    names = [s["name"] for s in r.json()["stops"]]
    assert "Central Campus Transit Center" in names


def test_arrivals_returns_board_and_leave():
    eta_at = datetime.now(UTC) + timedelta(minutes=6)
    etas = [EtaRecord(route_id="CN", stop_id="C251", vehicle_id="v1",
                      predicted_arrival_at=eta_at, captured_at=datetime.now(UTC))]
    client = TestClient(build_app(_service(etas)))
    r = client.get("/api/arrivals", params={"stop_id": "C251", "walk_min": 2})
    body = r.json()
    assert r.status_code == 200
    assert len(body["arrivals"]) == 1
    assert body["arrivals"][0]["route_id"] == "CN"
    assert body["leave"]["route_id"] == "CN"
    assert body["leave"]["leave_in_min"] in (3, 4)  # ~6 min ETA minus 2 min walk


def test_arrivals_degrades_gracefully_on_upstream_error():
    client = TestClient(build_app(_service(raise_upstream=True)))
    r = client.get("/api/arrivals", params={"stop_id": "C251"})
    body = r.json()
    assert r.status_code == 200
    assert body["arrivals"] == []
    assert body["leave"] is None
    assert body["error"] == "upstream"
