"""MCP tool implementations. Each function is thin: format inputs, call a
service method, format the result. No SQL, no HTTP, no math here.
"""
from datetime import UTC, datetime
from typing import Any

import structlog

from umich_transit.core.service import TransitService

logger = structlog.get_logger(__name__)


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
            parts.append(
                f"Route {a['route_id']}: published {raw_min} min, "
                f"history suggests ~{adj_min} min. {a['adjustment_reason']}"
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


def prediction_accuracy_tool(
    svc: TransitService, route_id: str | None = None,
) -> dict[str, Any]:
    """Compare published and adjusted error on chronologically held-out data."""
    result = svc.prediction_accuracy(route_id=route_id)
    if result["status"] != "ready":
        result.setdefault("summary", "Not enough matched outcomes for a holdout evaluation.")
        return result
    metrics = result.get("metrics")
    if metrics is None:
        return _degraded_accuracy_result(result, ["metrics"])
    if not isinstance(metrics, dict):
        return _degraded_accuracy_result(result, ["metrics"])
    published = metrics.get("published")
    adjusted = metrics.get("adjusted")
    if not isinstance(published, dict) or not isinstance(adjusted, dict):
        offending_keys: list[str] = []
        if not isinstance(published, dict):
            offending_keys.append("published")
        if not isinstance(adjusted, dict):
            offending_keys.append("adjusted")
        return _degraded_accuracy_result(result, offending_keys)
    published_error = published.get("mean_absolute_error_s")
    adjusted_error = adjusted.get("mean_absolute_error_s")
    if not isinstance(published_error, (int, float)) or isinstance(published_error, bool):
        return _degraded_accuracy_result(result, ["published.mean_absolute_error_s"])
    if not isinstance(adjusted_error, (int, float)) or isinstance(adjusted_error, bool):
        return _degraded_accuracy_result(result, ["adjusted.mean_absolute_error_s"])
    published_min = float(published_error) / 60
    adjusted_min = float(adjusted_error) / 60
    evidence = metrics.get("sample_count", result["holdout_sample_count"])
    if not isinstance(evidence, (int, float)) or isinstance(evidence, bool):
        return _degraded_accuracy_result(result, ["sample_count"])
    evidence_count = int(evidence)
    classification = str(metrics.get("classification", "unknown"))
    result["summary"] = (
        f"On {evidence_count} held-out arrivals, published predictions "
        f"averaged {published_min:.1f} min error versus {adjusted_min:.1f} min after "
        f"adjustment ({classification})."
    )
    return result


def _degraded_accuracy_result(result: dict[str, Any], offending_keys: list[str]) -> dict[str, Any]:
    result["status"] = "insufficient_data"
    result["summary"] = "The evaluation report could not be interpreted."
    logger.warning(
        "prediction_accuracy.malformed_report",
        offending_keys=offending_keys,
    )
    return result


async def plan_trip_tool(
    svc: TransitService, from_stop_id: str, to_stop_id: str,
) -> dict[str, Any]:
    """Plan a single-route bus trip from one stop to another (v1: no transfers)."""
    return await svc.plan_trip(from_stop_id=from_stop_id, to_stop_id=to_stop_id)
