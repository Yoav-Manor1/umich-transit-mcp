"""Tests for the MCP server command-line entry point."""
from contextlib import AsyncExitStack

import pytest

from umich_transit.mcp_server import __main__ as mcp_main


class FakeMcp:
    def __init__(self):
        self.ran = False

    async def run_stdio_async(self):
        self.ran = True


@pytest.mark.asyncio
async def test_run_enters_stack_and_awaits_stdio(monkeypatch):
    mcp = FakeMcp()
    stack = AsyncExitStack()
    events: list[str] = []

    async def on_exit():
        events.append("exited")

    stack.push_async_callback(on_exit)
    monkeypatch.setattr(mcp_main, "build_server", lambda: (mcp, stack))

    await mcp_main._run()

    assert mcp.ran
    assert events == ["exited"]


def test_main_runs_async_server(monkeypatch):
    seen: list[object] = []

    def fake_run(coro):
        seen.append(coro)
        coro.close()

    monkeypatch.setattr(mcp_main.asyncio, "run", fake_run)

    mcp_main.main()

    assert len(seen) == 1
