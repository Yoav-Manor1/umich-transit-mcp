"""Tests for application configuration helpers."""
from pathlib import Path

from pydantic import SecretStr

from umich_transit.config import Settings


def _settings(database_url: str) -> Settings:
    return Settings(
        mbus_base_url="https://mbus.example.test",
        mbus_api_key=SecretStr("test-key"),
        database_url=database_url,
        prediction_poll_seconds=120,
        arrival_poll_seconds=30,
        arrival_enter_meters=30.0,
        arrival_exit_meters=50.0,
        reliability_lookback_seconds=300,
        log_level="INFO",
    )


def test_sqlite_path_returns_file_path():
    assert _settings("sqlite:///./data/transit.db").sqlite_path == Path("./data/transit.db")


def test_sqlite_path_returns_none_for_memory_database():
    assert _settings("sqlite:///:memory:").sqlite_path is None


def test_sqlite_path_returns_none_for_non_sqlite_database():
    assert _settings("postgresql://localhost/transit").sqlite_path is None
