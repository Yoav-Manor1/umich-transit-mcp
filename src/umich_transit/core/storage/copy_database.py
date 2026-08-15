"""Count-verified database copying for the SQLite-to-PostgreSQL rollout."""

from sqlalchemy import Engine, func, select

from umich_transit.core.storage.models import Base


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
                for table in tables:
                    rows = [
                        dict(row._mapping)
                        for row in source_connection.execute(select(table)).all()
                    ]
                    if rows:
                        destination_connection.execute(table.insert(), rows)
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
            source_transaction.commit()
        except BaseException:
            source_transaction.rollback()
            raise
    return dict(sorted(copied.items()))
