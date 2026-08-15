"""Behavior of the deterministic, database-free public demo service."""

from datetime import UTC, datetime, timedelta

import pytest

from umich_transit.demo.service import DemoTransitService

NOW = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)


def _service() -> DemoTransitService:
    return DemoTransitService(now_factory=lambda: NOW)


def test_demo_stop_search_is_case_insensitive():
    stops = _service().find_stops(query="CENTRAL", limit=5)
    assert [stop["id"] for stop in stops] == ["CCTC"]
    assert stops[0]["name"] == "Central Campus Transit Center"


@pytest.mark.asyncio
async def test_demo_arrivals_shift_relative_to_now():
    arrivals = await _service().get_arrivals(stop_id="CCTC")
    assert arrivals[0]["predicted_arrival_at"] == NOW + timedelta(minutes=4)
    assert arrivals[0]["adjusted_arrival_at"] == NOW + timedelta(minutes=8)
    assert arrivals[0]["data_source"] == "demo"


@pytest.mark.asyncio
async def test_demo_arrivals_filter_routes_and_keep_order():
    arrivals = await _service().get_arrivals(stop_id="CCTC", route_id="CN")
    assert [arrival["route_id"] for arrival in arrivals] == ["CN", "CN"]
    assert [arrival["predicted_arrival_at"] for arrival in arrivals] == sorted(
        arrival["predicted_arrival_at"] for arrival in arrivals
    )


@pytest.mark.asyncio
async def test_demo_unknown_stop_has_no_arrivals():
    assert await _service().get_arrivals(stop_id="missing") == []


def test_demo_accuracy_is_explicitly_illustrative():
    report = _service().prediction_accuracy()
    assert report["status"] == "illustrative"
    assert report["data_source"] == "demo"
    assert report["sample_count"] == 120
    assert report["published"]["mean_absolute_error_s"] == 198
    assert report["adjusted"]["mean_absolute_error_s"] == 126


def test_demo_readiness_identifies_fixture_source():
    assert _service().readiness() == {
        "status": "ready",
        "mode": "demo",
        "data_source": "versioned_fixture",
        "fixture_version": 1,
    }
