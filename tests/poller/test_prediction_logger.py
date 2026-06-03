"""Tests for the prediction logger: takes ETA records, writes Prediction rows."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from umich_transit.core.clients.base import EtaRecord
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Base, Prediction, Route, Stop
from umich_transit.poller.prediction_logger import log_predictions


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with session_scope(eng) as s:
        s.add(Route(id="r1", agency="mbus", short_name="X", long_name="X"))
        s.add(Stop(id="s1", agency="mbus", name="N", lat=0, lon=0))
    return eng


def test_log_predictions_inserts_one_row_per_eta(engine):
    now = datetime.now(UTC)
    etas = [
        EtaRecord(route_id="r1", stop_id="s1", vehicle_id="v1",
                  predicted_arrival_at=now + timedelta(minutes=2), captured_at=now),
        EtaRecord(route_id="r1", stop_id="s1", vehicle_id="v2",
                  predicted_arrival_at=now + timedelta(minutes=5), captured_at=now),
    ]
    with session_scope(engine) as s:
        log_predictions(s, etas)
    with session_scope(engine) as s:
        rows = list(s.execute(select(Prediction)).scalars().all())
        assert len(rows) == 2
        assert {r.vehicle_id for r in rows} == {"v1", "v2"}


def test_log_predictions_skips_unknown_routes(engine):
    now = datetime.now(UTC)
    etas = [
        EtaRecord(route_id="unknown_route", stop_id="s1", vehicle_id="v1",
                  predicted_arrival_at=now, captured_at=now),
    ]
    with session_scope(engine) as s:
        log_predictions(s, etas)
    with session_scope(engine) as s:
        assert s.execute(select(Prediction)).scalars().first() is None


def test_log_predictions_handles_empty_list(engine):
    with session_scope(engine) as s:
        log_predictions(s, [])  # should not raise
