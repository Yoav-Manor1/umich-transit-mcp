"""Dialect-specific SQL construction kept behind one storage boundary."""

from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.sql.base import Executable

from umich_transit.core.storage.models import ReliabilityStat

BIN_KEY = ["route_id", "stop_id", "dow", "hour"]
DERIVED_FIELDS = [
    "on_time_pct",
    "mean_delay_s",
    "p50_delay_s",
    "p90_delay_s",
    "sample_count",
    "updated_at",
]


def build_reliability_upsert(
    dialect_name: str,
    values: Mapping[str, Any],
) -> Executable:
    """Build an equivalent reliability-stat upsert for SQLite or PostgreSQL."""
    table = cast(Table, ReliabilityStat.__table__)
    if dialect_name == "sqlite":
        statement = sqlite_insert(table).values(**values)
        return statement.on_conflict_do_update(
            index_elements=BIN_KEY,
            set_={field: getattr(statement.excluded, field) for field in DERIVED_FIELDS},
        )
    if dialect_name == "postgresql":
        statement_pg = postgresql_insert(table).values(**values)
        return statement_pg.on_conflict_do_update(
            index_elements=BIN_KEY,
            set_={field: getattr(statement_pg.excluded, field) for field in DERIVED_FIELDS},
        )
    raise ValueError(f"Unsupported database dialect: {dialect_name}")
