"""Tests for the web dashboard command-line entry point."""
from umich_transit.web import __main__ as web_main


def test_main_builds_app_runs_uvicorn_and_opens_browser(monkeypatch):
    app = object()
    calls: dict[str, object] = {}

    class FakeTimer:
        def __init__(self, delay, callback):
            calls["delay"] = delay
            calls["callback"] = callback

        def start(self):
            calls["started"] = True

    monkeypatch.setattr(web_main, "threading", type("Threading", (), {"Timer": FakeTimer}))
    monkeypatch.setattr(web_main, "webbrowser", type(
        "WebBrowser", (), {"open": lambda url: calls.setdefault("url", url)}
    ))
    monkeypatch.setattr(web_main, "build_app", lambda: app)
    monkeypatch.setattr(
        web_main, "uvicorn",
        type("Uvicorn", (), {"run": lambda actual, **kwargs: calls.update(
            {"app": actual, **kwargs}
        )}),
    )

    web_main.main()
    calls["callback"]()

    assert calls["app"] is app
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8000
    assert calls["url"] == "http://127.0.0.1:8000"
    assert calls["started"] is True
