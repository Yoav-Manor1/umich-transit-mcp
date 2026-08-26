"""Tests for the poller's DB-loader helpers (the testable, non-loop parts)."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from umich_transit.config import settings
from umich_transit.core.clients.base import EtaRecord, VehicleRecord
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Arrival, Base, Prediction, Route, RouteStop, Stop
from umich_transit.poller import runner
from umich_transit.poller.runner import (
    _load_detector_context,
    _load_route_ids,
    _load_stop_ids,
)


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with session_scope(eng) as s:
        s.add(Route(id="r1", agency="mbus", short_name="BB", long_name="Bursley-Baits"))
        s.add(Stop(id="s1", agency="mbus", name="A", lat=42.0, lon=-83.0))
        s.add(Stop(id="s2", agency="mbus", name="B", lat=42.1, lon=-83.1))
        s.add(RouteStop(route_id="r1", stop_id="s2", sequence=2))
        s.add(RouteStop(route_id="r1", stop_id="s1", sequence=1))
    return eng


def test_load_route_ids(engine):
    assert _load_route_ids(engine) == ["r1"]


def test_load_stop_ids(engine):
    assert sorted(_load_stop_ids(engine)) == ["s1", "s2"]


def test_load_detector_context_orders_stops_by_sequence(engine):
    stops, route_stops = _load_detector_context(engine)
    assert {s.id for s in stops} == {"s1", "s2"}
    # route_stops ordered by sequence -> s1 (seq 1) before s2 (seq 2)
    assert route_stops == {"r1": ["s1", "s2"]}


class StopLoop(BaseException):
    pass


def _sleep_that_stops_after(delays: list[float], stop_after: int):
    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) >= stop_after:
            raise StopLoop

    return fake_sleep


@pytest.mark.asyncio
async def test_prediction_loop_logs_predictions_and_uses_configured_interval(
    engine, monkeypatch,
):
    now = datetime.now(UTC)
    client = AsyncMock()
    client.get_etas_for_stops.return_value = [
        EtaRecord(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            predicted_arrival_at=now + timedelta(minutes=2), captured_at=now,
        ),
    ]
    delays: list[float] = []
    monkeypatch.setattr(
        "umich_transit.poller.runner.asyncio.sleep",
        _sleep_that_stops_after(delays, 1),
    )

    with pytest.raises(StopLoop):
        await runner._prediction_loop(engine, client)

    client.get_etas_for_stops.assert_awaited_once_with(["s1", "s2"])
    with session_scope(engine) as session:
        rows = list(session.execute(select(Prediction)).scalars())
        assert len(rows) == 1
        assert rows[0].vehicle_id == "v1"
    assert delays == [settings.prediction_poll_seconds]


@pytest.mark.asyncio
async def test_prediction_loop_backs_off_after_errors(engine, monkeypatch):
    client = AsyncMock()
    client.get_etas_for_stops.side_effect = RuntimeError("upstream")
    delays: list[float] = []
    monkeypatch.setattr(
        "umich_transit.poller.runner.asyncio.sleep",
        _sleep_that_stops_after(delays, 3),
    )

    with pytest.raises(StopLoop):
        await runner._prediction_loop(engine, client)

    assert delays[:2] == [1.0, 2.0]


@pytest.mark.asyncio
async def test_arrival_loop_writes_detected_arrival(engine, monkeypatch):
    now = datetime.now(UTC)
    client = AsyncMock()
    client.get_vehicle_positions.return_value = [
        VehicleRecord(
            id="v1", route_id="r1", lat=42.0000, lon=-83.0005,
            captured_at=now,
        ),
        VehicleRecord(
            id="v1", route_id="r1", lat=42.0000, lon=-83.00020,
            captured_at=now + timedelta(seconds=15),
        ),
    ]
    delays: list[float] = []
    monkeypatch.setattr(
        "umich_transit.poller.runner.asyncio.sleep",
        _sleep_that_stops_after(delays, 1),
    )

    with pytest.raises(StopLoop):
        await runner._arrival_loop(engine, client)

    client.get_vehicle_positions.assert_awaited_once_with(["r1"])
    with session_scope(engine) as session:
        arrival = session.execute(select(Arrival)).scalar_one()
        assert arrival.route_id == "r1"
        assert arrival.stop_id == "s1"
        assert arrival.vehicle_id == "v1"
    assert delays == [settings.arrival_poll_seconds]


@pytest.mark.asyncio
async def test_arrival_loop_backs_off_after_errors(engine, monkeypatch):
    client = AsyncMock()
    client.get_vehicle_positions.side_effect = RuntimeError("upstream")
    delays: list[float] = []
    monkeypatch.setattr(
        "umich_transit.poller.runner.asyncio.sleep",
        _sleep_that_stops_after(delays, 3),
    )

    with pytest.raises(StopLoop):
        await runner._arrival_loop(engine, client)

    assert delays[:2] == [1.0, 2.0]


@pytest.mark.asyncio
async def test_stats_loop_runs_jobs_and_uses_daily_interval(engine, monkeypatch):
    analytics = SimpleNamespace(
        matched_outcomes=4, profile_count=2, evaluation_status="ready",
    )

    def recompute(*args, **kwargs):
        return 7

    def refresh(*args):
        return analytics

    monkeypatch.setattr(runner, "recompute_all_bins", recompute)
    monkeypatch.setattr(runner, "refresh_showcase_analytics", refresh)
    delays: list[float] = []
    monkeypatch.setattr(
        "umich_transit.poller.runner.asyncio.sleep",
        _sleep_that_stops_after(delays, 1),
    )

    with pytest.raises(StopLoop):
        await runner._stats_loop(engine)

    assert delays == [24 * 3600]


@pytest.mark.asyncio
async def test_stats_loop_swallows_job_errors_and_continues_to_sleep(engine, monkeypatch):
    monkeypatch.setattr(
        runner, "recompute_all_bins", lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("stats failed")
        ),
    )
    delays: list[float] = []
    monkeypatch.setattr(
        "umich_transit.poller.runner.asyncio.sleep",
        _sleep_that_stops_after(delays, 1),
    )

    with pytest.raises(StopLoop):
        await runner._stats_loop(engine)

    assert delays == [24 * 3600]


@pytest.mark.asyncio
async def test_run_starts_all_three_loops_with_configured_client(monkeypatch):
    engine = object()
    monkeypatch.setattr(runner, "create_engine_for_url", lambda url: engine)
    calls: list[tuple[str, object, object]] = []

    class FakeClient:
        def __init__(self, *, base_url, api_key, http):
            calls.append((base_url, api_key, http))

    monkeypatch.setattr(runner, "MbusClient", FakeClient)
    completed: list[str] = []

    async def prediction(fake_engine, client):
        assert fake_engine is engine
        completed.append("prediction")

    async def arrival(fake_engine, client):
        assert fake_engine is engine
        completed.append("arrival")

    async def stats(fake_engine):
        assert fake_engine is engine
        completed.append("stats")

    monkeypatch.setattr(runner, "_prediction_loop", prediction)
    monkeypatch.setattr(runner, "_arrival_loop", arrival)
    monkeypatch.setattr(runner, "_stats_loop", stats)

    await runner.run()

    assert set(completed) == {"prediction", "arrival", "stats"}
    assert calls[0][0] == settings.mbus_base_url
    assert calls[0][1] == settings.mbus_api_key.get_secret_value()
