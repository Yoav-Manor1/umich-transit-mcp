#!/usr/bin/env python3
"""Copy collected transit data into a migrated destination database."""

import argparse
import os
from collections.abc import Sequence

from sqlalchemy.engine import make_url

from umich_transit.core.storage.copy_database import copy_database
from umich_transit.core.storage.db import create_engine_for_url


def redact_database_url(url: str) -> str:
    """Render a database URL without exposing its password."""
    return make_url(url).render_as_string(hide_password=True)


def validate_database_urls(source_url: str, destination_url: str) -> None:
    """Reject malformed or identical migration endpoints."""
    for label, value in (("source", source_url), ("destination", destination_url)):
        if "://" not in value:
            raise ValueError(f"{label} must be a complete SQLAlchemy URL")
        make_url(value)
    if make_url(source_url) == make_url(destination_url):
        raise ValueError("Source and destination must be different databases")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy U-Mich Transit data after migrating the destination schema."
    )
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--destination-url", required=True)
    parser.add_argument("--replace", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    validate_database_urls(args.source_url, args.destination_url)

    # Alembic's environment reads DATABASE_URL when it imports application
    # settings. Set it before importing Alembic's command module.
    os.environ["DATABASE_URL"] = args.destination_url
    from alembic import command
    from alembic.config import Config

    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")

    source = create_engine_for_url(args.source_url)
    destination = create_engine_for_url(args.destination_url)
    counts = copy_database(source, destination, replace=args.replace)

    print(
        "Copied data from "
        f"{redact_database_url(args.source_url)} to "
        f"{redact_database_url(args.destination_url)}"
    )
    for table_name, count in counts.items():
        print(f"{table_name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
