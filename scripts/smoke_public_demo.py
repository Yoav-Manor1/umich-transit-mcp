#!/usr/bin/env python3
"""Verify the public recruiter journey against a local or deployed demo."""

import argparse
from collections.abc import Sequence
from typing import Any, Protocol, cast

import httpx


class SmokeCheckError(RuntimeError):
    """A required public-demo behavior did not pass verification."""


class ResponseLike(Protocol):
    status_code: int
    text: str

    def json(self) -> Any: ...


class ClientLike(Protocol):
    def get(self, url: str) -> ResponseLike: ...


def _require(condition: bool, check: str, detail: str) -> None:
    if not condition:
        raise SmokeCheckError(f"{check} failed: {detail}")


def run_smoke(base_url: str, *, client: ClientLike | None = None) -> list[str]:
    """Run the complete public demo contract and return passed check names."""
    owned_client: httpx.Client | None = None
    if client is None:
        owned_client = httpx.Client(timeout=15.0, follow_redirects=True)
    active_client = cast(ClientLike, owned_client if client is None else client)
    root = base_url.rstrip("/")
    passed: list[str] = []
    try:
        landing = active_client.get(f"{root}/")
        _require(landing.status_code == 200, "landing page", str(landing.status_code))
        _require("Demo data" in landing.text, "landing page", "demo label missing")
        _require("github.com/Yoav-Manor1" in landing.text, "landing page", "GitHub link missing")
        _require('href="#methodology"' in landing.text, "landing page", "method link missing")
        passed.append("landing page")

        health = active_client.get(f"{root}/api/health")
        health_body = health.json()
        _require(health.status_code == 200, "health", str(health.status_code))
        _require(health_body == {"status": "ok", "mode": "demo"}, "health", str(health_body))
        passed.append("health")

        ready = active_client.get(f"{root}/api/ready")
        ready_body = ready.json()
        _require(ready.status_code == 200, "readiness", str(ready.status_code))
        _require(
            ready_body.get("data_source") == "versioned_fixture",
            "readiness",
            str(ready_body),
        )
        passed.append("readiness")

        stops = active_client.get(f"{root}/api/stops/search?q=central")
        stops_body = stops.json()
        _require(stops.status_code == 200, "stop search", str(stops.status_code))
        _require(
            any(stop.get("id") == "CCTC" for stop in stops_body.get("stops", [])),
            "stop search",
            "CCTC missing",
        )
        passed.append("stop search")

        arrivals = active_client.get(f"{root}/api/arrivals?stop_id=CCTC&walk_min=5")
        arrivals_body = arrivals.json()
        _require(arrivals.status_code == 200, "arrivals", str(arrivals.status_code))
        _require(bool(arrivals_body.get("arrivals")), "arrivals", "no demo arrivals")
        _require(arrivals_body.get("leave") is not None, "arrivals", "leave guidance missing")
        _require(
            arrivals_body["arrivals"][0].get("data_source") == "demo",
            "arrivals",
            "demo source missing",
        )
        passed.append("arrivals")

        accuracy = active_client.get(f"{root}/api/accuracy")
        accuracy_body = accuracy.json()
        _require(accuracy.status_code == 200, "accuracy", str(accuracy.status_code))
        _require(
            accuracy_body.get("status") == "illustrative",
            "accuracy",
            "illustrative status missing",
        )
        passed.append("accuracy")

        css = active_client.get(f"{root}/static/style.css")
        _require(css.status_code == 200, "static CSS", str(css.status_code))
        _require(len(css.text) > 1000, "static CSS", "stylesheet appears truncated")
        passed.append("static CSS")
    finally:
        if owned_client is not None:
            owned_client.close()
    return passed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test the Honest ETA public demo.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--base-url")
    target.add_argument("--local", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.local:
        from fastapi.testclient import TestClient

        from umich_transit.config import Settings
        from umich_transit.web.runtime import build_runtime_app

        config = Settings(transit_app_mode="demo", vercel=False)
        with TestClient(build_runtime_app(config)) as test_client:
            checks = run_smoke("http://testserver", client=test_client)
    else:
        checks = run_smoke(args.base_url)
    for check in checks:
        print(f"PASS {check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
