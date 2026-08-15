"""Safe, count-verified copying between SQLAlchemy databases."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from scripts.migrate_database import redact_database_url, validate_database_urls
from umich_transit.core.storage.copy_database import copy_database
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import (
    Arrival,
    Base,
    ParseError,
    Prediction,
    ReliabilityStat,
    Route,
    RouteStop,
    Stop,
)

NOW = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)


def _engines(tmp_path):
    source = create_engine_for_url(f"sqlite:///{tmp_path / 'source.db'}")
    destination = create_engine_for_url(f"sqlite:///{tmp_path / 'destination.db'}")
    Base.metadata.create_all(source)
    Base.metadata.create_all(destination)
    return source, destination


def _seed_source(engine) -> None:
    with session_scope(engine) as session:
        session.add(
            Route(
                id="CN",
                agency="mbus",
                short_name="CN",
                long_name="Commuter North",
                raw_json={"rt": "CN"},
                updated_at=NOW,
            )
        )
        session.add(
            Stop(
                id="CCTC",
                agency="mbus",
                name="Central Campus Transit Center",
                lat=42.2786,
                lon=-83.7346,
                raw_json={"stpid": "CCTC"},
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(RouteStop(route_id="CN", stop_id="CCTC", sequence=1))
        session.add(
            Prediction(
                route_id="CN",
                stop_id="CCTC",
                vehicle_id="v1",
                predicted_arrival_at=NOW + timedelta(minutes=4),
                captured_at=NOW,
            )
        )
        session.add(
            Arrival(
                route_id="CN",
                stop_id="CCTC",
                vehicle_id="v1",
                actual_arrival_at=NOW + timedelta(minutes=8),
                detected_via="proximity",
            )
        )
        session.add(
            ReliabilityStat(
                route_id="CN",
                stop_id="CCTC",
                dow=5,
                hour=12,
                on_time_pct=0.64,
                mean_delay_s=240,
                p50_delay_s=210,
                p90_delay_s=420,
                sample_count=72,
                updated_at=NOW,
            )
        )
        session.add(
            ParseError(
                source="mbus.etas",
                occurred_at=NOW,
                error="fixture error",
                raw={"bad": True},
            )
        )


def _count(engine, model) -> int:
    with session_scope(engine) as session:
        return int(session.execute(select(func.count()).select_from(model)).scalar_one())


def test_copy_database_preserves_rows_and_source(tmp_path):
    source, destination = _engines(tmp_path)
    _seed_source(source)

    counts = copy_database(source, destination)

    assert counts == {
        "arrivals": 1,
        "parse_errors": 1,
        "predictions": 1,
        "reliability_stats": 1,
        "route_stops": 1,
        "routes": 1,
        "stops": 1,
    }
    assert _count(source, Prediction) == 1
    assert _count(destination, Prediction) == 1


def test_copy_database_refuses_nonempty_destination(tmp_path):
    source, destination = _engines(tmp_path)
    _seed_source(source)
    copy_database(source, destination)

    with pytest.raises(ValueError, match="destination is not empty"):
        copy_database(source, destination)


def test_copy_database_replace_is_explicit_and_idempotent(tmp_path):
    source, destination = _engines(tmp_path)
    _seed_source(source)
    copy_database(source, destination)

    counts = copy_database(source, destination, replace=True)

    assert counts["predictions"] == 1
    assert _count(destination, Prediction) == 1


def test_copy_database_rejects_same_database(tmp_path):
    source, _ = _engines(tmp_path)
    with pytest.raises(ValueError, match="different databases"):
        copy_database(source, source)


def test_cli_validation_rejects_missing_url_scheme():
    with pytest.raises(ValueError, match="SQLAlchemy URL"):
        validate_database_urls("data/source.db", "postgresql://u:p@host/db")


def test_cli_validation_rejects_identical_urls():
    with pytest.raises(ValueError, match="different databases"):
        validate_database_urls("sqlite:///data.db", "sqlite:///data.db")


def test_database_url_redaction_never_returns_password():
    redacted = redact_database_url("postgresql://yoav:super-secret@host/transit")
    assert redacted == "postgresql://yoav:***@host/transit"
    assert "super-secret" not in redacted
