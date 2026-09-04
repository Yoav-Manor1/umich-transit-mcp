"""The public smoke check exercises the deployed recruiter journey."""

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from scripts.smoke_public_demo import SmokeCheckError, run_smoke
from umich_transit.demo.service import DemoTransitService
from umich_transit.web.app import build_app


def test_smoke_check_covers_the_public_demo_contract():
    client = TestClient(build_app(DemoTransitService(), app_mode="demo"))

    checks = run_smoke("http://testserver", client=client)

    assert checks == [
        "landing page",
        "JavaScript asset",
        "health",
        "readiness",
        "stop search",
        "selected stop arrivals",
        "accuracy",
        "static CSS",
    ]


def test_smoke_check_fails_on_an_unhealthy_deployment():
    app = FastAPI()

    @app.get("/{path:path}")
    def unavailable(path: str):
        del path
        return Response(status_code=500)

    with pytest.raises(SmokeCheckError, match="landing page"):
        run_smoke("http://testserver", client=TestClient(app))
