"""Tests for the web dashboard HTTP endpoints."""
from fastapi.testclient import TestClient

from umich_transit.web.app import build_app


def test_health_ok():
    client = TestClient(build_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
