"""Tests for the nightly stats recomputation job."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import (
    Arrival,
    Base,
    Prediction,
    ReliabilityStat,
    Route,
    Stop,
)
from umich_transit.poller.stats_job import recompute_all_bins


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with session_scope(eng) as s:
        s.add(Route(id="r1", agency="mbus", short_name="X", long_name="X"))
        s.add(Stop(id="s1", agency="mbus", name="N", lat=0, lon=0))
    return eng


def _seed_pair(session, *, dow_hour: datetime, late_seconds: int) -> None:
    """Insert one prediction + one arrival representing the same trip."""
    arrival = dow_hour
    prediction_captured = arrival - timedelta(seconds=60)
    predicted = arrival - timedelta(seconds=late_seconds)
    session.add(Prediction(
        route_id="r1", stop_id="s1", vehicle_id="v1",
        predicted_arrival_at=predicted, captured_at=prediction_captured,
    ))
    session.add(Arrival(
        route_id="r1", stop_id="s1", vehicle_id="v1",
        actual_arrival_at=arrival, detected_via="proximity",
    ))


def test_recompute_creates_stat_row(engine):
    base = datetime(2026, 4, 6, 8, 30, tzinfo=UTC)  # Monday 08:xx
    with session_scope(engine) as s:
        _seed_pair(s, dow_hour=base, late_seconds=60)
        _seed_pair(s, dow_hour=base + timedelta(minutes=10), late_seconds=180)
    recompute_all_bins(engine, lookback_seconds=300, on_time_threshold_s=120)
    with session_scope(engine) as s:
        stat = s.execute(select(ReliabilityStat)).scalar_one()
        assert stat.sample_count == 2
        # One delay 60s (on-time), one 180s (late) -> 50% on-time
        assert stat.on_time_pct == pytest.approx(0.5)
        assert stat.mean_delay_s == pytest.approx(120.0)


def test_recompute_idempotent(engine):
    base = datetime(2026, 4, 6, 8, 30, tzinfo=UTC)
    with session_scope(engine) as s:
        _seed_pair(s, dow_hour=base, late_seconds=60)
    recompute_all_bins(engine, lookback_seconds=300, on_time_threshold_s=120)
    recompute_all_bins(engine, lookback_seconds=300, on_time_threshold_s=120)
    with session_scope(engine) as s:
        stats = list(s.execute(select(ReliabilityStat)).scalars().all())
        assert len(stats) == 1  # upserted, not duplicated


def test_recompute_skips_arrivals_with_no_matching_prediction(engine):
    base = datetime(2026, 4, 6, 8, 30, tzinfo=UTC)
    with session_scope(engine) as s:
        s.add(Arrival(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            actual_arrival_at=base, detected_via="proximity",
        ))
    recompute_all_bins(engine, lookback_seconds=300, on_time_threshold_s=120)
    with session_scope(engine) as s:
        assert s.execute(select(ReliabilityStat)).scalars().first() is None
