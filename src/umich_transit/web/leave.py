"""Pure 'when should I leave?' computation for the dashboard banner.

Given the arrivals dicts returned by TransitService.get_arrivals (which carry
both a published and a reliability-adjusted ETA plus a confidence label) and the
user's walk time to the stop, decide when to leave for the soonest catchable bus.
"""
from datetime import datetime
from math import ceil
from typing import Any


def _effective_eta(item: dict[str, Any]) -> datetime:
    """Use the adjusted ETA only when we trust it (high confidence), else the
    published one — the same convention as mcp_server/tools.get_arrivals_tool."""
    key = (
        "adjusted_arrival_at"
        if item.get("confidence") in {"high", "medium"}
        else "predicted_arrival_at"
    )
    eta = item[key]
    assert isinstance(eta, datetime)
    return eta


def compute_leave(
    arrivals: list[dict[str, Any]], walk_min: int, now: datetime
) -> dict[str, Any] | None:
    """Return the leave-now banner data, or None if there is no upcoming bus."""
    upcoming = [a for a in arrivals if _effective_eta(a) >= now]
    if not upcoming:
        return None
    target = min(upcoming, key=_effective_eta)
    eta = _effective_eta(target)
    minutes_until = ceil((eta - now).total_seconds() / 60)
    leave_in_min = max(0, minutes_until - walk_min)
    return {
        "leave_in_min": leave_in_min,
        "minutes_until": minutes_until,
        "route_id": target["route_id"],
        "arrival_at": eta.isoformat(),
        "confidence": target.get("confidence", "low"),
    }
