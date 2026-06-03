"""Read-only queries used by the service layer.

All functions take a Session; none manage transactions themselves.
"""
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

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


def _haversine_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Great-circle distance between two (lat, lon) points, in meters."""
    r_earth_m = 6_371_000.0
    p1, p2 = radians(a_lat), radians(b_lat)
    dphi = radians(b_lat - a_lat)
    dlam = radians(b_lon - a_lon)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlam / 2) ** 2
    return 2 * r_earth_m * asin(sqrt(a))


def find_stops(
    session: Session,
    query: str = "",
    near: tuple[float, float] | None = None,
    limit: int = 5,
) -> list[Stop]:
    stmt = select(Stop)
    if query:
        stmt = stmt.where(Stop.name.ilike(f"%{query}%"))
    rows = list(session.execute(stmt).scalars().all())
    if near is not None:
        lat, lon = near
        rows.sort(key=lambda s: _haversine_m(lat, lon, s.lat, s.lon))
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
    session: Session, *, vehicle_id: str, stop_id: str,
    arrival_at: datetime, lookback_seconds: int,
) -> Prediction | None:
    """Find the prediction captured ~lookback_seconds before the arrival.

    Returns the most recent prediction within the window
    [arrival_at - lookback_seconds, arrival_at].
    """
    window_start = arrival_at - timedelta(seconds=lookback_seconds)
    stmt = (
        select(Prediction)
        .where(
            Prediction.vehicle_id == vehicle_id,
            Prediction.stop_id == stop_id,
            Prediction.captured_at >= window_start,
            Prediction.captured_at <= arrival_at,
        )
        .order_by(Prediction.captured_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()
