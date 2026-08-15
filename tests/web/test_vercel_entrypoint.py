"""Vercel imports the same FastAPI app exercised by local tests."""

import importlib
import json
import sys
from pathlib import Path

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


def test_vercel_uses_fastapi_auto_detection_in_demo_mode():
    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))

    assert config["env"]["TRANSIT_APP_MODE"] == "demo"
    assert config["functions"]["api/index.py"]["includeFiles"] == "src/umich_transit/**"
    assert config["rewrites"] == [{"source": "/(.*)", "destination": "/api/index"}]


def test_file_based_vercel_entrypoint_exports_the_same_app(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TRANSIT_APP_MODE", "demo")
    sys.modules.pop("api.index", None)

    module = importlib.import_module("api.index")

    assert isinstance(module.app, FastAPI)
