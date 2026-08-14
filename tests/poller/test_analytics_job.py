"""Tests for rebuilding persisted showcase analytics."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import (
    Arrival,
    Base,
    EvaluationReportRow,
    Prediction,
    ReliabilityProfileRow,
    Route,
    Stop,
)
from umich_transit.poller.analytics_job import refresh_showcase_analytics


def test_refresh_persists_profiles_and_ready_holdout_report():
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    base = datetime(2024, 1, 1, 13, 0, tzinfo=UTC)
    with session_scope(engine) as session:
        session.add(Route(id="r1", agency="mbus", short_name="R1", long_name="Route 1"))
        session.add(Stop(id="s1", agency="mbus", name="Stop 1", lat=42, lon=-83))
        for index in range(100):
            actual = base + timedelta(days=7 * index)
            vehicle_id = f"v{index}"
            session.add(Prediction(
                route_id="r1", stop_id="s1", vehicle_id=vehicle_id,
                captured_at=actual - timedelta(seconds=300),
                predicted_arrival_at=actual - timedelta(seconds=60),
            ))
            session.add(Arrival(
                route_id="r1", stop_id="s1", vehicle_id=vehicle_id,
                actual_arrival_at=actual, detected_via="proximity",
            ))

    result = refresh_showcase_analytics(engine)

    assert result.matched_outcomes == 100
    assert result.evaluation_status == "ready"
    with session_scope(engine) as session:
        profile_count = session.scalar(select(func.count()).select_from(ReliabilityProfileRow))
        assert profile_count == 6  # Two local hours across each of the three scopes.
        report = session.execute(
            select(EvaluationReportRow).order_by(EvaluationReportRow.id.desc())
        ).scalar_one()
        assert report.holdout_sample_count == 20
        assert report.metrics_json is not None
        assert report.metrics_json["classification"] == "improved"
        routes = report.metrics_json["routes"]
        assert isinstance(routes, dict)
        assert routes["r1"]["classification"] == "improved"
