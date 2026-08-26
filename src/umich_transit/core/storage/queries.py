"""Read-only queries used by the service layer.

All functions take a Session; none manage transactions themselves.
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from umich_transit.core.geo import haversine_m
from umich_transit.core.storage.models import (
    Arrival,
    Prediction,
    ReliabilityStat,
    Route,
    Stop,
)


def list_routes(session: Session, agency: str | None = None) -> list[Route]:
    stmt = select(Route)
    if agency is not None:
        stmt = stmt.where(Route.agency == agency)
    stmt = stmt.order_by(Route.agency, Route.short_name)
    return list(session.execute(stmt).scalars().all())

def find_stops(
    session: Session,
    query: str = "",
    near: tuple[float, float] | None = None,
    limit: int = 5,
) -> list[Stop]:
    stmt = select(Stop)
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Stop.name.ilike(f"%{escaped}%", escape="\\"))
    rows = list(session.execute(stmt).scalars().all())
    if near is not None:
        lat, lon = near
        rows.sort(key=lambda s: haversine_m(lat, lon, s.lat, s.lon))
    else:
        rows.sort(key=lambda s: s.name)
    return rows[:limit]


def get_reliability_stat(
    session: Session, *, route_id: str, stop_id: str, dow: int, hour: int,
) -> ReliabilityStat | None:
    stmt = select(ReliabilityStat).where(
        ReliabilityStat.route_id == route_id,
        ReliabilityStat.stop_id == stop_id,
        ReliabilityStat.dow == dow,
        ReliabilityStat.hour == hour,
    )
    return session.execute(stmt).scalar_one_or_none()


def arrivals_in_window(
    session: Session, *, route_id: str, stop_id: str,
    since: datetime, until: datetime,
) -> list[Arrival]:
    stmt = select(Arrival).where(
        Arrival.route_id == route_id,
        Arrival.stop_id == stop_id,
        Arrival.actual_arrival_at >= since,
        Arrival.actual_arrival_at <= until,
    ).order_by(Arrival.actual_arrival_at)
    return list(session.execute(stmt).scalars().all())


def prediction_for_arrival(
    session: Session, *, vehicle_id: str, route_id: str, stop_id: str,
    arrival_at: datetime, target_horizon_seconds: int,
    tolerance_seconds: int,
) -> Prediction | None:
    """Find the prediction captured closest to a fixed pre-arrival horizon."""
    target = arrival_at - timedelta(seconds=target_horizon_seconds)
    window_start = target - timedelta(seconds=tolerance_seconds)
    window_end = target + timedelta(seconds=tolerance_seconds)
    stmt = select(Prediction).where(
        Prediction.vehicle_id == vehicle_id,
        Prediction.route_id == route_id,
        Prediction.stop_id == stop_id,
        Prediction.captured_at >= window_start,
        Prediction.captured_at <= window_end,
        Prediction.predicted_arrival_at >= Prediction.captured_at,
    )
    candidates = list(session.execute(stmt).scalars().all())
    if not candidates:
        return None
    return min(candidates, key=lambda p: (abs(p.captured_at - target), p.captured_at))
