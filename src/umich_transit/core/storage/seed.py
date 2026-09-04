"""Seed static data (routes, stops, route_stops) from a Magic Bus client.

Idempotent: re-running upserts rows rather than duplicating. Stops are
deduplicated across routes; route_stops captures the per-route stop sequence.
"""
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.sql.base import Executable

from umich_transit.core.clients.base import RouteRecord, StopRecord
from umich_transit.core.storage.db import session_scope
from umich_transit.core.storage.models import Route, RouteStop, Stop


class _StaticDataClient(Protocol):
    async def get_routes(self) -> list[RouteRecord]: ...
    async def get_pattern_stops(self, route_id: str) -> list[tuple[int, StopRecord]]: ...


def build_route_upsert(
    dialect_name: str, route: RouteRecord, updated_at: datetime
) -> Executable:
    """Build the route upsert using the destination engine's SQL dialect."""
    values = {
        "id": route.id,
        "agency": route.agency,
        "short_name": route.short_name,
        "long_name": route.long_name,
        "color": route.color,
        "raw_json": route.raw,
        "updated_at": updated_at,
    }
    updates = {
        "short_name": route.short_name,
        "long_name": route.long_name,
        "color": route.color,
        "raw_json": route.raw,
        "updated_at": updated_at,
    }
    if dialect_name == "sqlite":
        return sqlite_insert(Route).values(**values).on_conflict_do_update(
            index_elements=[Route.id], set_=updates
        )
    if dialect_name == "postgresql":
        return postgresql_insert(Route).values(**values).on_conflict_do_update(
            index_elements=[Route.id], set_=updates
        )
    raise ValueError(f"Unsupported database dialect: {dialect_name}")


def build_stop_upsert(
    dialect_name: str, stop: StopRecord, updated_at: datetime
) -> Executable:
    """Build the stop upsert using the destination engine's SQL dialect."""
    values = {
        "id": stop.id,
        "agency": stop.agency,
        "name": stop.name,
        "lat": stop.lat,
        "lon": stop.lon,
        "raw_json": stop.raw,
        "updated_at": updated_at,
    }
    updates = {
        "name": stop.name,
        "lat": stop.lat,
        "lon": stop.lon,
        "raw_json": stop.raw,
        "updated_at": updated_at,
    }
    if dialect_name == "sqlite":
        return sqlite_insert(Stop).values(**values).on_conflict_do_update(
            index_elements=[Stop.id], set_=updates
        )
    if dialect_name == "postgresql":
        return postgresql_insert(Stop).values(**values).on_conflict_do_update(
            index_elements=[Stop.id], set_=updates
        )
    raise ValueError(f"Unsupported database dialect: {dialect_name}")


def build_route_stop_insert(
    dialect_name: str, route_id: str, stop_id: str, sequence: int
) -> Executable:
    """Build an idempotent route-stop insert for SQLite or PostgreSQL."""
    values = {"route_id": route_id, "stop_id": stop_id, "sequence": sequence}
    conflict_columns = [RouteStop.route_id, RouteStop.stop_id, RouteStop.sequence]
    if dialect_name == "sqlite":
        return sqlite_insert(RouteStop).values(**values).on_conflict_do_nothing(
            index_elements=conflict_columns
        )
    if dialect_name == "postgresql":
        return postgresql_insert(RouteStop).values(**values).on_conflict_do_nothing(
            index_elements=conflict_columns
        )
    raise ValueError(f"Unsupported database dialect: {dialect_name}")


async def seed_static_data(
    engine: Engine, client: _StaticDataClient,
) -> tuple[int, int, int]:
    """Fetch routes + per-route pattern stops, upsert into the DB.

    Returns (route_count, unique_stop_count, route_stop_link_count) where the
    link count is the total number of route-stop relationships processed
    (idempotent re-runs report the same total even though no new rows are
    inserted).
    All network calls happen first; a single transaction does the writes.
    """
    routes = await client.get_routes()
    patterns: dict[str, list[tuple[int, StopRecord]]] = {}
    for r in routes:
        patterns[r.id] = await client.get_pattern_stops(r.id)

    now = datetime.now(UTC)
    seen_stops: set[str] = set()
    link_count = 0

    with session_scope(engine) as session:
        for r in routes:
            session.execute(build_route_upsert(engine.dialect.name, r, now))

        for route_id, stops in patterns.items():
            for seq, st in stops:
                if st.id not in seen_stops:
                    session.execute(build_stop_upsert(engine.dialect.name, st, now))
                    seen_stops.add(st.id)
                session.execute(
                    build_route_stop_insert(engine.dialect.name, route_id, st.id, seq)
                )
                link_count += 1

    return len(routes), len(seen_stops), link_count
