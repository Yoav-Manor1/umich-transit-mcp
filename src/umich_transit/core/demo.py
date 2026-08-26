"""Deterministic showcase data kept separate from live transit observations."""
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine

from umich_transit.core.clients.base import EtaRecord
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import (
    Arrival,
    Base,
    Prediction,
    Route,
    RouteStop,
    Stop,
)
from umich_transit.core.time import AGENCY_TIMEZONE
from umich_transit.poller.analytics_job import refresh_showcase_analytics

DEMO_ROUTES = (
    ("CN", "Commuter North", "#2F65A7", "CCTC", "Central Campus Transit Center", 180),
    ("BB", "Bursley-Baits", "#702082", "PIERPONT", "Pierpont Commons", 90),
    ("CS", "Commuter South", "#007E3A", "BURSLEY", "Bursley Hall", -60),
)
DEMO_RESIDUAL_SECONDS = (-60, -30, 0, 30, 60)


class DemoMbusClient(MbusClient):
    """Small deterministic feed whose timestamps stay relative to each request."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    async def get_etas(self, stop_id: str) -> list[EtaRecord]:
        now = self._clock()
        route = next((item for item in DEMO_ROUTES if item[3] == stop_id), None)
        if route is None:
            return []
        route_id = route[0]
        return [
            EtaRecord(
                route_id=route_id,
                stop_id=stop_id,
                vehicle_id=f"demo-{route_id}-1",
                predicted_arrival_at=now + timedelta(minutes=6),
                captured_at=now,
            ),
            EtaRecord(
                route_id=route_id,
                stop_id=stop_id,
                vehicle_id=f"demo-{route_id}-2",
                predicted_arrival_at=now + timedelta(minutes=16),
                captured_at=now,
            ),
        ]


def build_demo_service(
    database_url: str,
    *,
    now: datetime | None = None,
    live_clock: Callable[[], datetime] | None = None,
) -> tuple[TransitService, Engine]:
    """Rebuild a dedicated demo database and return its service and engine."""
    demo_path = _validate_demo_url(database_url)
    if demo_path is not None:
        demo_path.parent.mkdir(parents=True, exist_ok=True)
    moment = now or datetime.now(UTC)
    engine = create_engine_for_url(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    _seed_demo_history(engine, moment)
    refresh_showcase_analytics(engine)
    return TransitService(engine=engine, mbus=DemoMbusClient(live_clock)), engine


def _seed_demo_history(engine: Engine, now: datetime) -> None:
    anchor = (
        now.astimezone(AGENCY_TIMEZONE).replace(minute=0, second=0, microsecond=0)
        - timedelta(weeks=1)
    )
    with session_scope(engine) as session:
        for route in DEMO_ROUTES:
            route_id, route_name, color, stop_id, stop_name, error_s = route
            session.add(Route(
                id=route_id, agency="mbus", short_name=route_id,
                long_name=route_name, color=color,
            ))
            session.add(Stop(
                id=stop_id, agency="mbus", name=stop_name,
                lat=42.28, lon=-83.74,
            ))

    with session_scope(engine) as session:
        for route_index, route in enumerate(DEMO_ROUTES):
            route_id, _route_name, _color, stop_id, _stop_name, error_s = route
            session.add(RouteStop(route_id=route_id, stop_id=stop_id, sequence=1))
            for week in range(100):
                local = anchor - timedelta(weeks=99 - week)
                actual = local.astimezone(UTC) + timedelta(minutes=route_index * 10)
                vehicle_id = f"demo-{route_id}-{week}"
                signed_error_s = error_s + DEMO_RESIDUAL_SECONDS[week % 5]
                session.add(Prediction(
                    route_id=route_id,
                    stop_id=stop_id,
                    vehicle_id=vehicle_id,
                    captured_at=actual - timedelta(seconds=300),
                    predicted_arrival_at=actual - timedelta(seconds=signed_error_s),
                ))
                session.add(Arrival(
                    route_id=route_id,
                    stop_id=stop_id,
                    vehicle_id=vehicle_id,
                    actual_arrival_at=actual,
                    detected_via="proximity",
                ))


def _validate_demo_url(database_url: str) -> Path | None:
    if database_url == "sqlite:///:memory:":
        return None
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("Demo mode requires a dedicated SQLite database")
    path = Path(database_url[len(prefix):])
    if "demo" not in path.name.lower():
        raise ValueError("Demo database filename must contain 'demo'")
    return path
