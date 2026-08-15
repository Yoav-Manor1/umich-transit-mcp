"""Public-page contracts that keep the recruiter showcase understandable."""

from fastapi.testclient import TestClient

from umich_transit.demo.service import DemoTransitService
from umich_transit.web.app import build_app


def _client() -> TestClient:
    return TestClient(build_app(DemoTransitService(), app_mode="demo"))


def test_landing_page_explains_the_outcome_and_demo_state():
    response = _client().get("/")
    assert response.status_code == 200
    page = response.text
    assert "Magic Bus says four minutes" in page
    assert "Demo data" in page
    assert "Live board" in page
    assert "Accuracy" in page
    assert "How it works" in page


def test_landing_page_exposes_accessible_views_and_project_links():
    page = _client().get("/").text
    assert 'role="tablist"' in page
    assert 'aria-controls="live-view"' in page
    assert 'aria-controls="accuracy-view"' in page
    assert "github.com/Yoav-Manor1/umich-transit-mcp" in page
    assert 'href="#methodology"' in page


def test_public_static_assets_are_served():
    client = _client()
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
