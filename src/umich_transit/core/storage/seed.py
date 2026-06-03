"""Seed static data (routes, stops, route_stops) from a Magic Bus client.

Idempotent: re-running upserts rows rather than duplicating. Stops are
deduplicated across routes; route_stops captures the per-route stop sequence.
"""
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Engine
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from umich_transit.core.clients.base import RouteRecord, StopRecord
from umich_transit.core.storage.db import session_scope
from umich_transit.core.storage.models import Route, RouteStop, Stop


class _StaticDataClient(Protocol):
    async def get_routes(self) -> list[RouteRecord]: ...
    async def get_pattern_stops(self, route_id: str) -> list[tuple[int, StopRecord]]: ...


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
            session.execute(
                sqlite_insert(Route)
                .values(
                    id=r.id, agency=r.agency, short_name=r.short_name,
                    long_name=r.long_name, color=r.color, raw_json=r.raw,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[Route.id],
                    set_={
                        "short_name": r.short_name, "long_name": r.long_name,
                        "color": r.color, "raw_json": r.raw, "updated_at": now,
                    },
                )
            )

        for route_id, stops in patterns.items():
            for seq, st in stops:
                if st.id not in seen_stops:
                    session.execute(
                        sqlite_insert(Stop)
                        .values(
                            id=st.id, agency=st.agency, name=st.name,
                            lat=st.lat, lon=st.lon, raw_json=st.raw,
                            updated_at=now,
                        )
                        .on_conflict_do_update(
                            index_elements=[Stop.id],
                            set_={
                                "name": st.name, "lat": st.lat, "lon": st.lon,
                                "raw_json": st.raw, "updated_at": now,
                            },
                        )
                    )
                    seen_stops.add(st.id)
                session.execute(
                    sqlite_insert(RouteStop)
                    .values(route_id=route_id, stop_id=st.id, sequence=seq)
                    .on_conflict_do_nothing(
                        index_elements=[
                            RouteStop.route_id, RouteStop.stop_id, RouteStop.sequence,
                        ]
                    )
                )
                link_count += 1

    return len(routes), len(seen_stops), link_count
