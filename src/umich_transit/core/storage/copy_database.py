"""Count-verified database copying for the SQLite-to-PostgreSQL rollout."""

from collections.abc import Mapping

from sqlalchemy import Engine, func, select, text
from sqlalchemy.engine import Connection

from umich_transit.core.storage.models import Base

_SERIAL_PRIMARY_KEYS = {
    "predictions": "id",
    "arrivals": "id",
    "parse_errors": "id",
}


def _advance_postgresql_sequences(
    connection: Connection,
    copied_max_ids: Mapping[str, int],
) -> None:
    """Advance serial sequences after inserting explicit IDs in PostgreSQL."""
    for table_name, last_id in copied_max_ids.items():
        column_name = _SERIAL_PRIMARY_KEYS[table_name]
        sequence_name = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
            {"table_name": table_name, "column_name": column_name},
        ).scalar_one_or_none()
        if sequence_name is None:
            continue
        connection.execute(
            text(
                "SELECT setval(CAST(:sequence_name AS regclass), :last_id, true)"
            ),
            {"sequence_name": sequence_name, "last_id": last_id},
        )


def copy_database(
    source: Engine,
    destination: Engine,
    *,
    replace: bool = False,
) -> dict[str, int]:
    """Copy every application table without modifying the source database."""
    if source is destination or source.url == destination.url:
        raise ValueError("Source and destination must be different databases")

    tables = list(Base.metadata.sorted_tables)
    with source.connect() as source_connection:
        source_transaction = source_connection.begin()
        try:
            with destination.begin() as destination_connection:
                existing = {
                    table.name: int(
                        destination_connection.execute(
                            select(func.count()).select_from(table)
                        ).scalar_one()
                    )
                    for table in tables
                }
                if any(existing.values()) and not replace:
                    raise ValueError("destination is not empty; pass replace=True to overwrite")
                if replace:
                    for table in reversed(tables):
                        destination_connection.execute(table.delete())

                copied: dict[str, int] = {}
                copied_max_ids: dict[str, int] = {}
                for table in tables:
                    rows = [
                        dict(row._mapping)
                        for row in source_connection.execute(select(table)).all()
                    ]
                    if rows:
                        destination_connection.execute(table.insert(), rows)
                        if table.name in _SERIAL_PRIMARY_KEYS:
                            primary_key = _SERIAL_PRIMARY_KEYS[table.name]
                            copied_max_ids[table.name] = max(
                                int(row[primary_key]) for row in rows
                            )
                    destination_count = int(
                        destination_connection.execute(
                            select(func.count()).select_from(table)
                        ).scalar_one()
                    )
                    if destination_count != len(rows):
                        raise RuntimeError(
                            f"Row-count mismatch for {table.name}: "
                            f"source={len(rows)} destination={destination_count}"
                        )
                    copied[table.name] = destination_count
                if destination_connection.dialect.name == "postgresql":
                    _advance_postgresql_sequences(
                        destination_connection, copied_max_ids
                    )
            source_transaction.commit()
        except BaseException:
            source_transaction.rollback()
            raise
    return dict(sorted(copied.items()))
