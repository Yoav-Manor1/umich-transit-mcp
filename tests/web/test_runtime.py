"""Runtime-mode behavior for local and deployed web applications."""

import pytest

from umich_transit.web.runtime import resolve_app_mode


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
