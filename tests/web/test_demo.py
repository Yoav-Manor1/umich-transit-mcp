"""Tests for the deterministic web showcase entry point."""
from umich_transit.web import demo


def test_main_builds_demo_app_runs_uvicorn_and_opens_browser(monkeypatch):
    app = object()
    calls: dict[str, object] = {}

    class FakeTimer:
        def __init__(self, delay, callback):
            calls["delay"] = delay
            calls["callback"] = callback

        def start(self):
            calls["started"] = True

    class FakePath:
        def __init__(self, value):
            calls["path"] = value

        def mkdir(self, exist_ok=False):
            calls["mkdir_exist_ok"] = exist_ok

    monkeypatch.setattr(demo, "Path", FakePath)
    monkeypatch.setattr(demo, "threading", type("Threading", (), {"Timer": FakeTimer}))
    monkeypatch.setattr(demo, "webbrowser", type(
        "WebBrowser", (), {"open": lambda url: calls.setdefault("url", url)}
    ))
    monkeypatch.setattr(demo, "build_demo_app", lambda: app)
    monkeypatch.setattr(
        demo, "uvicorn",
        type("Uvicorn", (), {"run": lambda actual, **kwargs: calls.update(
            {"app": actual, **kwargs}
        )}),
    )

    demo.main()
    calls["callback"]()

    assert calls["path"] == "data"
    assert calls["mkdir_exist_ok"] is True
    assert calls["app"] is app
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8000
    assert calls["url"] == "http://127.0.0.1:8000"
    assert calls["started"] is True
