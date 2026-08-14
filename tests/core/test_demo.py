"""Tests for the deterministic, isolated showcase dataset."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from umich_transit.core.demo import build_demo_service
from umich_transit.core.storage.db import session_scope
from umich_transit.core.storage.models import EvaluationReportRow, PredictionOutcome


async def test_demo_service_builds_ready_evidence_and_relative_arrivals():
    now = datetime(2026, 8, 14, 16, 0, tzinfo=UTC)

    service, engine = build_demo_service("sqlite:///:memory:", now=now)

    with session_scope(engine) as session:
        outcome_count = session.scalar(select(func.count()).select_from(PredictionOutcome))
        report = session.execute(
            select(EvaluationReportRow).order_by(EvaluationReportRow.id.desc())
        ).scalar_one()
    arrivals = await service.get_arrivals(stop_id="CCTC", now=now)
    assert outcome_count == 300
    assert report.status == "ready"
    assert report.metrics_json is not None
    assert report.metrics_json["classification"] == "improved"
    assert report.metrics_json["adjusted"]["mean_absolute_error_s"] > 0
    assert (
        report.metrics_json["adjusted"]["mean_absolute_error_s"]
        < report.metrics_json["published"]["mean_absolute_error_s"]
    )
    assert set(report.metrics_json["routes"]) == {"CN", "BB", "CS"}
    assert arrivals
    assert arrivals[0]["predicted_arrival_at"] > now
    assert arrivals[0]["confidence"] in {"high", "medium"}


def test_demo_refuses_to_rebuild_a_non_demo_database(tmp_path):
    unsafe_url = f"sqlite:///{tmp_path / 'transit.db'}"

    with pytest.raises(ValueError, match="filename must contain 'demo'"):
        build_demo_service(unsafe_url)


def test_demo_builds_in_a_dedicated_file_database(tmp_path):
    demo_url = f"sqlite:///{tmp_path / 'demo-transit.db'}"

    _, engine = build_demo_service(demo_url)

    with session_scope(engine) as session:
        assert session.scalar(select(func.count()).select_from(PredictionOutcome)) == 300


def test_demo_creates_a_missing_parent_directory(tmp_path):
    demo_path = tmp_path / "fresh-checkout" / "demo-transit.db"

    _, engine = build_demo_service(f"sqlite:///{demo_path}")

    assert demo_path.exists()
    with session_scope(engine) as session:
        assert session.scalar(select(func.count()).select_from(PredictionOutcome)) == 300
