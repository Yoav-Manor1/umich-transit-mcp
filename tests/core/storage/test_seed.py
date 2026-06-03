"""Tests for static-data seeding (routes, stops, route_stops) from the client."""
import pytest
from sqlalchemy import func, select

from umich_transit.core.clients.base import RouteRecord, StopRecord
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Base, Route, RouteStop, Stop
from umich_transit.core.storage.seed import seed_static_data


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
    await seed_static_data(engine, FakeClient())
    with session_scope(engine) as s:
        r = s.get(Route, "CN")
        assert r.long_name == "Commuter North"
