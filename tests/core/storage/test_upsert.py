"""Reliability writes compile correctly for every supported SQL dialect."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from umich_transit.core.storage.upsert import build_reliability_upsert

VALUES = {
    "route_id": "CN",
    "stop_id": "CCTC",
    "dow": 4,
    "hour": 17,
    "on_time_pct": 0.7,
    "mean_delay_s": 120.0,
    "p50_delay_s": 90.0,
    "p90_delay_s": 300.0,
    "sample_count": 42,
    "updated_at": datetime(2026, 8, 15, tzinfo=UTC),
}


@pytest.mark.parametrize(
    ("dialect_name", "dialect"),
    [("sqlite", sqlite.dialect()), ("postgresql", postgresql.dialect())],
)
def test_reliability_upsert_targets_the_full_bin_key(dialect_name, dialect):
    statement = build_reliability_upsert(dialect_name, VALUES)
    sql = str(statement.compile(dialect=dialect)).replace("\n", " ")
    assert "ON CONFLICT (route_id, stop_id, dow, hour) DO UPDATE" in sql
    for column in (
        "on_time_pct",
        "mean_delay_s",
        "p50_delay_s",
        "p90_delay_s",
        "sample_count",
        "updated_at",
    ):
        assert f"{column} = excluded.{column}" in sql


def test_reliability_upsert_rejects_unknown_dialect():
    with pytest.raises(ValueError, match="Unsupported database dialect"):
        build_reliability_upsert("mysql", VALUES)
