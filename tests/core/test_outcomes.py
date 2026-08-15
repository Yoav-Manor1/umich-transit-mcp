"""Tests for rebuilding versioned prediction outcomes."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from umich_transit.core.outcomes import rebuild_prediction_outcomes
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import (
    Arrival,
    Base,
    Prediction,
    PredictionOutcome,
    Route,
    Stop,
)


def _engine():
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        session.add(Route(id="r1", agency="mbus", short_name="R1", long_name="Route 1"))
        session.add(Stop(id="s1", agency="mbus", name="Stop 1", lat=42.0, lon=-83.0))
    return engine


def test_rebuild_persists_horizon_and_error_for_fixed_horizon_match():
    engine = _engine()
    actual = datetime(2026, 8, 10, 14, 0, tzinfo=UTC)
    with session_scope(engine) as session:
        session.add(Prediction(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            captured_at=actual - timedelta(seconds=305),
            predicted_arrival_at=actual - timedelta(seconds=120),
        ))
        session.add(Arrival(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            actual_arrival_at=actual, detected_via="proximity",
        ))

    result = rebuild_prediction_outcomes(engine)

    assert result.matched == 1
    assert result.unmatched == 0
    with session_scope(engine) as session:
        outcome = session.execute(select(PredictionOutcome)).scalar_one()
        assert outcome.prediction_horizon_s == 305
        assert outcome.signed_error_s == 120
        assert outcome.absolute_error_s == 120
        assert outcome.match_version == "fixed-horizon-v1"


def test_rebuild_is_idempotent():
    engine = _engine()
    actual = datetime(2026, 8, 10, 14, 0, tzinfo=UTC)
    with session_scope(engine) as session:
        session.add(Prediction(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            captured_at=actual - timedelta(seconds=300),
            predicted_arrival_at=actual,
        ))
        session.add(Arrival(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            actual_arrival_at=actual, detected_via="proximity",
        ))

    rebuild_prediction_outcomes(engine)
    rebuild_prediction_outcomes(engine)

    with session_scope(engine) as session:
        assert len(list(session.execute(select(PredictionOutcome)).scalars())) == 1


def test_rebuild_reports_prediction_reuse_instead_of_double_matching():
    engine = _engine()
    actual = datetime(2026, 8, 10, 14, 0, tzinfo=UTC)
    with session_scope(engine) as session:
        session.add(Prediction(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            captured_at=actual - timedelta(seconds=300),
            predicted_arrival_at=actual,
        ))
        for offset in (0, 10):
            session.add(Arrival(
                route_id="r1", stop_id="s1", vehicle_id="v1",
                actual_arrival_at=actual + timedelta(seconds=offset),
                detected_via="proximity",
            ))

    result = rebuild_prediction_outcomes(engine)

    assert result.matched == 1
    assert result.unmatched == 1
    assert result.rejections == {"prediction_reused": 1}
