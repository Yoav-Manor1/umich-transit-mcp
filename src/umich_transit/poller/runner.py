"""Long-running poller. Three independent async tasks share one DB + client:
- prediction logger (every PREDICTION_POLL_SECONDS)
- arrival detector  (every ARRIVAL_POLL_SECONDS)
- stats recompute   (every 24h)

Each loop catches exceptions, backs off exponentially (capped), and continues
so one failing upstream call never kills the process.
"""
import asyncio

import httpx
import structlog
from sqlalchemy import Engine, select

from umich_transit.config import settings
from umich_transit.core.clients.base import StopRecord
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Arrival, Route, RouteStop, Stop
from umich_transit.poller.arrival_detector import ArrivalDetector
from umich_transit.poller.prediction_logger import log_predictions
from umich_transit.poller.stats_job import recompute_all_bins

logger = structlog.get_logger(__name__)

_MAX_BACKOFF_S = 60.0
_ON_TIME_THRESHOLD_S = 120.0


def _load_detector_context(
    engine: Engine,
) -> tuple[list[StopRecord], dict[str, list[str]]]:
    """Read stops and the route->stops mapping (ordered by sequence) from the DB."""
    with session_scope(engine) as session:
        stops = [
            StopRecord(id=r.id, agency=r.agency, name=r.name,
                       lat=r.lat, lon=r.lon, raw=r.raw_json or {})
            for r in session.execute(select(Stop)).scalars().all()
        ]
        route_stops: dict[str, list[str]] = {}
        rs_rows = session.execute(
            select(RouteStop).order_by(RouteStop.route_id, RouteStop.sequence)
        ).scalars().all()
        for rs in rs_rows:
            route_stops.setdefault(rs.route_id, []).append(rs.stop_id)
    return stops, route_stops


def _load_route_ids(engine: Engine) -> list[str]:
    with session_scope(engine) as session:
        return list(session.execute(select(Route.id)).scalars().all())


def _load_stop_ids(engine: Engine) -> list[str]:
    with session_scope(engine) as session:
        return list(session.execute(select(Stop.id)).scalars().all())


async def _prediction_loop(engine: Engine, client: MbusClient) -> None:
    backoff = 1.0
    while True:
        try:
            stop_ids = _load_stop_ids(engine)
            etas = []
            for stop_id in stop_ids:
                etas.extend(await client.get_etas(stop_id))
            with session_scope(engine) as session:
                inserted = log_predictions(session, etas)
            logger.info("prediction_loop.tick", stops=len(stop_ids), inserted=inserted)
            backoff = 1.0
        except Exception as exc:
            logger.warning("prediction_loop.error", error=str(exc), backoff=backoff)
            await asyncio.sleep(min(backoff, _MAX_BACKOFF_S))
            backoff = min(backoff * 2, _MAX_BACKOFF_S)
            continue
        await asyncio.sleep(settings.prediction_poll_seconds)


async def _arrival_loop(engine: Engine, client: MbusClient) -> None:
    stops, route_stops = _load_detector_context(engine)
    route_ids = _load_route_ids(engine)
    detector = ArrivalDetector(
        stops=stops,
        route_stops=route_stops,
        enter_meters=settings.arrival_enter_meters,
        exit_meters=settings.arrival_exit_meters,
    )
    backoff = 1.0
    while True:
        try:
            vehicles = await client.get_vehicle_positions(route_ids)
            events = []
            for vehicle in vehicles:
                events.extend(detector.observe(vehicle))
            if events:
                with session_scope(engine) as session:
                    for ev in events:
                        session.add(Arrival(
                            route_id=ev.route_id,
                            stop_id=ev.stop_id,
                            vehicle_id=ev.vehicle_id,
                            actual_arrival_at=ev.actual_arrival_at,
                            detected_via=ev.detected_via,
                        ))
            logger.info("arrival_loop.tick", vehicles=len(vehicles), arrivals=len(events))
            backoff = 1.0
        except Exception as exc:
            logger.warning("arrival_loop.error", error=str(exc), backoff=backoff)
            await asyncio.sleep(min(backoff, _MAX_BACKOFF_S))
            backoff = min(backoff * 2, _MAX_BACKOFF_S)
            continue
        await asyncio.sleep(settings.arrival_poll_seconds)


async def _stats_loop(engine: Engine) -> None:
    while True:
        try:
            written = recompute_all_bins(
                engine,
                lookback_seconds=settings.reliability_lookback_seconds,
                on_time_threshold_s=_ON_TIME_THRESHOLD_S,
            )
            logger.info("stats_loop.tick", bins=written)
        except Exception as exc:
            logger.error("stats_loop.error", error=str(exc))
        await asyncio.sleep(24 * 3600)


async def run() -> None:
    engine = create_engine_for_url(settings.database_url)
    async with httpx.AsyncClient(timeout=15.0) as http:
        client = MbusClient(
            base_url=settings.mbus_base_url,
            api_key=settings.mbus_api_key.get_secret_value(),
            http=http,
        )
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_prediction_loop(engine, client))
            tg.create_task(_arrival_loop(engine, client))
            tg.create_task(_stats_loop(engine))
