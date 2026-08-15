"""Vercel imports the same FastAPI app exercised by local tests."""

import importlib
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_vercel_entrypoint_exports_demo_fastapi(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TRANSIT_APP_MODE", "demo")
    sys.modules.pop("app", None)

    module = importlib.import_module("app")

    assert isinstance(module.app, FastAPI)
    with TestClient(module.app) as client:
        assert client.get("/api/health").json() == {
            "status": "ok",
            "mode": "demo",
        }
        assert client.get("/api/ready").json()["data_source"] == "versioned_fixture"
