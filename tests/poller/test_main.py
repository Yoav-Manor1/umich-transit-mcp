"""Tests for the poller command-line entry point."""
import logging

from umich_transit.poller import __main__ as poller_main


def test_main_configures_logging_and_runs_poller(monkeypatch):
    seen: list[object] = []

    def fake_run(coro):
        seen.append(coro)
        coro.close()

    configured: list[dict[str, object]] = []
    monkeypatch.setattr(poller_main.asyncio, "run", fake_run)
    monkeypatch.setattr(
        poller_main.structlog, "configure",
        lambda **kwargs: configured.append(kwargs),
    )

    poller_main.main()

    assert len(seen) == 1
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    assert configured
    assert configured[0]["processors"]


def test_main_handles_keyboard_interrupt(monkeypatch):
    def interrupted(coro):
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(poller_main.asyncio, "run", interrupted)

    poller_main.main()
