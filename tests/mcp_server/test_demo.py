"""Tests for the deterministic MCP showcase entry point."""
from contextlib import AsyncExitStack

import pytest

from umich_transit.mcp_server import demo


class FakeMcp:
    def __init__(self):
        self.ran = False

    async def run_stdio_async(self):
        self.ran = True


@pytest.mark.asyncio
async def test_run_enters_demo_stack_and_awaits_stdio(monkeypatch):
    mcp = FakeMcp()
    stack = AsyncExitStack()
    events: list[str] = []

    async def on_exit():
        events.append("exited")

    stack.push_async_callback(on_exit)
    monkeypatch.setattr(demo, "build_demo_server", lambda: (mcp, stack))

    await demo._run()

    assert mcp.ran
    assert events == ["exited"]


def test_main_runs_demo_mcp(monkeypatch):
    seen: list[object] = []

    def fake_run(coro):
        seen.append(coro)
        coro.close()

    monkeypatch.setattr(demo.asyncio, "run", fake_run)

    demo.main()

    assert len(seen) == 1
