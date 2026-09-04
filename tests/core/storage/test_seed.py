"""Tests for static-data seeding (routes, stops, route_stops) from the client."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from umich_transit.core.clients.base import RouteRecord, StopRecord
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Base, Route, RouteStop, Stop
from umich_transit.core.storage.seed import (
    build_route_stop_insert,
    build_route_upsert,
    build_stop_upsert,
    seed_static_data,
)


class FakeClient:
    """Minimal stand-in for MbusClient with canned routes + patterns."""

    def __init__(self):
        self._routes = [
            RouteRecord(id="BB", agency="mbus", short_name="BB",
                        long_name="Bursley-Baits", color="#00274c", raw={}),
            RouteRecord(id="CN", agency="mbus", short_name="CN",
                        long_name="Commuter North", color=None, raw={}),
        ]
        # BB visits s1 then s2; CN visits s2 then s3. s2 is shared.
        self._patterns = {
            "BB": [
                (1, StopRecord(id="s1", agency="mbus", name="Bursley",
                               lat=42.27, lon=-83.73, raw={})),
                (2, StopRecord(id="s2", agency="mbus", name="Pierpont",
                               lat=42.29, lon=-83.71, raw={})),
            ],
            "CN": [
                (1, StopRecord(id="s2", agency="mbus", name="Pierpont",
                               lat=42.29, lon=-83.71, raw={})),
                (2, StopRecord(id="s3", agency="mbus", name="North Campus",
                               lat=42.29, lon=-83.71, raw={})),
            ],
        }

    async def get_routes(self):
        return list(self._routes)

    async def get_pattern_stops(self, route_id):
        return list(self._patterns[route_id])


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


async def test_seed_inserts_routes_stops_and_links(engine):
    n_routes, n_stops, n_links = await seed_static_data(engine, FakeClient())
    assert n_routes == 2
    assert n_stops == 3   # s1, s2, s3 (s2 deduped across routes)
    assert n_links == 4   # BB:2 + CN:2 route_stop rows
    with session_scope(engine) as s:
        assert s.execute(select(func.count()).select_from(Route)).scalar() == 2
        assert s.execute(select(func.count()).select_from(Stop)).scalar() == 3
        assert s.execute(select(func.count()).select_from(RouteStop)).scalar() == 4


async def test_seed_is_idempotent(engine):
    await seed_static_data(engine, FakeClient())
    await seed_static_data(engine, FakeClient())  # run again
    with session_scope(engine) as s:
        assert s.execute(select(func.count()).select_from(Route)).scalar() == 2
        assert s.execute(select(func.count()).select_from(Stop)).scalar() == 3
        assert s.execute(select(func.count()).select_from(RouteStop)).scalar() == 4


async def test_seed_updates_existing_route_name(engine):
    client = FakeClient()
    await seed_static_data(engine, client)
    # Mutate upstream data and re-seed: the upsert should UPDATE the row.
    client._routes[1] = RouteRecord(
        id="CN", agency="mbus", short_name="CN",
        long_name="Commuter North (renamed)", color=None, raw={},
    )
    await seed_static_data(engine, client)
    with session_scope(engine) as s:
        r = s.get(Route, "CN")
        assert r.long_name == "Commuter North (renamed)"


def test_seed_statements_compile_for_postgresql():
    now = datetime(2026, 8, 15, tzinfo=UTC)
    route = FakeClient()._routes[0]
    stop = FakeClient()._patterns["BB"][0][1]

    route_sql = str(
        build_route_upsert("postgresql", route, now).compile(
            dialect=postgresql.dialect()
        )
    )
    stop_sql = str(
        build_stop_upsert("postgresql", stop, now).compile(
            dialect=postgresql.dialect()
        )
    )
    link_sql = str(
        build_route_stop_insert("postgresql", "BB", "s1", 1).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "ON CONFLICT (id) DO UPDATE" in route_sql
    assert "ON CONFLICT (id) DO UPDATE" in stop_sql
    assert "ON CONFLICT (route_id, stop_id, sequence) DO NOTHING" in link_sql
