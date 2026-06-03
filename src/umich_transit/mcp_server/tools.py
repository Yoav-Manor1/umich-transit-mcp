"""MCP tool implementations. Each function is thin: format inputs, call a
service method, format the result. No SQL, no HTTP, no math here.
"""
from datetime import UTC, datetime
from typing import Any

from umich_transit.core.service import TransitService


def list_routes_tool(svc: TransitService, agency: str | None = None) -> dict[str, Any]:
    """List bus routes, optionally filtered by agency ('mbus' / 'theride')."""
    routes = svc.list_routes(agency=agency)
    n = len(routes)
    summary = f"{n} route{'s' if n != 1 else ''} found"
    if agency:
        summary += f" for agency={agency}"
    return {"summary": summary, "routes": routes}


def find_stops_tool(
    svc: TransitService,
    query: str = "",
    near: list[float] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Find bus stops by name, optionally sorted by distance to [lat, lon]."""
    near_tuple = (near[0], near[1]) if near and len(near) >= 2 else None
    stops = svc.find_stops(query=query, near=near_tuple, limit=limit)
    n = len(stops)
    return {
        "summary": f"{n} stop{'s' if n != 1 else ''} matching '{query}'",
        "stops": stops,
    }


async def get_arrivals_tool(
    svc: TransitService,
    stop_id: str,
    route_id: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Upcoming arrivals at a stop with both the published ETA and a
    reliability-adjusted ETA."""
    arrivals = await svc.get_arrivals(stop_id=stop_id, route_id=route_id, limit=limit)
    if not arrivals:
        return {"summary": "No upcoming arrivals at this stop.", "arrivals": []}
    now = datetime.now(UTC)
    parts: list[str] = []
    for a in arrivals:
        raw_min = max(0, int((a["predicted_arrival_at"] - now).total_seconds() // 60))
        adj_min = max(0, int((a["adjusted_arrival_at"] - now).total_seconds() // 60))
        if a["confidence"] == "high" and adj_min != raw_min:
            on_time = a["on_time_pct_at_this_hour"] or 0.0
            parts.append(
                f"Route {a['route_id']}: published {raw_min} min, "
                f"history suggests ~{adj_min} min "
                f"({on_time:.0%} on-time, n={a['sample_size']})"
            )
        else:
            parts.append(
                f"Route {a['route_id']}: {raw_min} min (confidence: {a['confidence']})"
            )
    return {"summary": " | ".join(parts), "arrivals": arrivals}


def route_reliability_tool(
    svc: TransitService,
    route_id: str,
    day_of_week: int | None = None,
    hour: int | None = None,
) -> dict[str, Any]:
    """Reliability stats for a route (on-time %, mean delay, samples).
    day_of_week: 0=Mon..6=Sun; hour: 0..23."""
    return svc.route_reliability(route_id=route_id, day_of_week=day_of_week, hour=hour)
