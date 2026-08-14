"""Integration tests for upgrading the on-disk schema."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from umich_transit.config import settings


def test_upgrade_head_creates_showcase_analytics_tables(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    tables = inspect(create_engine(database_url)).get_table_names()
    assert {
        "prediction_outcomes",
        "reliability_profiles",
        "evaluation_reports",
    } <= set(tables)
