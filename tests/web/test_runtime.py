"""Runtime-mode behavior for local and deployed web applications."""

import pytest
from pydantic import SecretStr

from umich_transit.config import Settings
from umich_transit.demo.service import DemoTransitService
from umich_transit.web.runtime import build_runtime_service, resolve_app_mode


def test_explicit_demo_mode_is_allowed_on_vercel():
    assert resolve_app_mode("demo", on_vercel=True) == "demo"


def test_local_mode_is_default_off_vercel():
    assert resolve_app_mode(None, on_vercel=False) == "local"


def test_vercel_requires_explicit_mode():
    with pytest.raises(ValueError, match="TRANSIT_APP_MODE"):
        resolve_app_mode(None, on_vercel=True)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="local, demo, or live"):
        resolve_app_mode("preview", on_vercel=False)


def test_demo_service_needs_no_database_or_bus_key():
    config = Settings(
        _env_file=None,
        database_url="not-a-database-url",
        mbus_api_key=SecretStr(""),
    )
    service, http = build_runtime_service("demo", config)
    assert isinstance(service, DemoTransitService)
    assert http is None


def test_live_vercel_mode_rejects_sqlite():
    config = Settings(
        _env_file=None,
        vercel=True,
        database_url="sqlite:///data/transit.db",
        mbus_api_key=SecretStr("configured"),
    )
    with pytest.raises(ValueError, match="PostgreSQL"):
        build_runtime_service("live", config)


def test_live_mode_rejects_missing_bus_key():
    config = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@example.test/transit",
        mbus_api_key=SecretStr(""),
    )
    with pytest.raises(ValueError, match="MBUS_API_KEY"):
        build_runtime_service("live", config)
