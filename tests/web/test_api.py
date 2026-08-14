"""Tests for the web dashboard HTTP endpoints."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from umich_transit.core.clients.base import EtaRecord
from umich_transit.core.clients.mbus import BusTimeError
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Base, EvaluationReportRow, Route, Stop
from umich_transit.web.app import build_app
from umich_transit.web.demo import build_demo_app


def _service(etas=None, raise_upstream=False, with_evaluation=False):
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with session_scope(engine) as s:
        s.add(Route(id="CN", agency="mbus", short_name="CN", long_name="Commuter North"))
        s.add(Stop(id="C251", agency="mbus",
                   name="Central Campus Transit Center", lat=42.27, lon=-83.73))
        if with_evaluation:
            s.add(EvaluationReportRow(
                generated_at=datetime(2026, 8, 14, tzinfo=UTC), status="ready",
                total_sample_count=100, training_sample_count=80, holdout_sample_count=20,
                match_version="fixed-horizon-v1", model_version="median-hierarchy-v1",
                metrics_json={
                    "classification": "improved",
                    "published": {"mean_absolute_error_s": 180.0},
                    "adjusted": {"mean_absolute_error_s": 90.0},
                },
            ))
    mbus = AsyncMock()
    if raise_upstream:
        mbus.get_etas = AsyncMock(side_effect=BusTimeError("bad key"))
    else:
        mbus.get_etas = AsyncMock(return_value=etas or [])
    return TransitService(engine=engine, mbus=mbus)


def test_health_ok():
    client = TestClient(build_app(_service()))
    assert client.get("/api/health").json() == {"status": "ok"}


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


def test_accuracy_returns_shared_holdout_report():
    client = TestClient(build_app(_service(with_evaluation=True)))

    response = client.get("/api/accuracy")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["metrics"]["classification"] == "improved"


def test_static_showcase_assets_are_served():
    client = TestClient(build_app(_service()))

    assert client.get("/").status_code == 200
    javascript = client.get("/static/app.js")
    html = client.get("/")
    assert javascript.status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert "prompt(" not in javascript.text
    assert 'id="walk-minutes"' in html.text


def test_meta_explicitly_labels_demo_mode():
    client = TestClient(build_app(_service(), demo_mode=True))

    assert client.get("/api/meta").json() == {"demo_mode": True}


def test_demo_app_starts_with_ready_accuracy_and_searchable_stops(tmp_path):
    app = build_demo_app(f"sqlite:///{tmp_path / 'demo-web.db'}")
    client = TestClient(app)

    assert client.get("/api/meta").json() == {"demo_mode": True}
    assert client.get("/api/accuracy").json()["status"] == "ready"
    stops = client.get("/api/stops/search", params={"q": "central"}).json()["stops"]
    assert stops[0]["id"] == "CCTC"
