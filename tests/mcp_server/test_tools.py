"""Tests for MCP tool implementations (called directly; the adapter is thin)."""
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from umich_transit.mcp_server import tools


def _service_with_routes():
    svc = MagicMock()
    svc.list_routes.return_value = [
        {"id": "r1", "agency": "mbus", "short_name": "BB",
         "long_name": "Bursley-Baits", "color": None},
    ]
    return svc


def test_list_routes_tool_returns_summary_and_data():
    svc = _service_with_routes()
    result = tools.list_routes_tool(svc, agency=None)
    assert "summary" in result
    assert result["routes"][0]["short_name"] == "BB"
    assert "1 route" in result["summary"]


def test_list_routes_tool_passes_agency_filter():
    svc = _service_with_routes()
    tools.list_routes_tool(svc, agency="mbus")
    svc.list_routes.assert_called_with(agency="mbus")


def test_find_stops_tool():
    svc = MagicMock()
    svc.find_stops.return_value = [
        {"id": "s1", "agency": "mbus", "name": "Mason Hall", "lat": 42.27, "lon": -83.74},
    ]
    result = tools.find_stops_tool(svc, query="mason", near=None, limit=5)
    assert result["stops"][0]["name"] == "Mason Hall"
    assert "stops" in result


def test_find_stops_tool_converts_near_list_to_tuple():
    svc = MagicMock()
    svc.find_stops.return_value = []
    tools.find_stops_tool(svc, query="", near=[42.1, -83.7], limit=3)
    # near should be passed to the service as a (lat, lon) tuple
    _, kwargs = svc.find_stops.call_args
    assert kwargs["near"] == (42.1, -83.7)


def test_get_arrivals_tool_passes_through_and_summarizes():
    now = datetime.now(UTC)
    svc = MagicMock()
    svc.get_arrivals = AsyncMock(return_value=[{
        "route_id": "r1", "stop_id": "s1", "vehicle_id": "v1",
        "predicted_arrival_at": now + timedelta(minutes=4),
        "adjusted_arrival_at": now + timedelta(minutes=10),
        "on_time_pct_at_this_hour": 0.6, "sample_size": 80, "confidence": "high",
    }])
    result = asyncio.run(tools.get_arrivals_tool(svc, stop_id="s1", route_id=None, limit=5))
    assert result["arrivals"][0]["route_id"] == "r1"
    assert "r1" in result["summary"]
    assert isinstance(result["summary"], str)


def test_get_arrivals_tool_empty():
    svc = MagicMock()
    svc.get_arrivals = AsyncMock(return_value=[])
    result = asyncio.run(tools.get_arrivals_tool(svc, stop_id="s1", route_id=None, limit=5))
    assert result["arrivals"] == []
    assert "No upcoming" in result["summary"] or "no upcoming" in result["summary"].lower()


def test_route_reliability_tool():
    svc = MagicMock()
    svc.route_reliability.return_value = {
        "route_id": "r1", "sample_count": 200, "mean_delay_s": 180.0,
        "on_time_pct": 0.7, "summary": "70% on-time across 200 arrivals; avg delay 180s",
    }
    result = tools.route_reliability_tool(svc, route_id="r1", day_of_week=None, hour=None)
    assert result["sample_count"] == 200


def test_plan_trip_tool():
    svc = MagicMock()
    svc.plan_trip = AsyncMock(return_value={
        "summary": "Take route r1 (vehicle v1) from s1 to s2",
        "plan": {"segments": [{"route_id": "r1"}]},
    })
    result = asyncio.run(tools.plan_trip_tool(svc, from_stop_id="s1", to_stop_id="s2"))
    assert "r1" in result["summary"]
    assert result["plan"]["segments"][0]["route_id"] == "r1"
