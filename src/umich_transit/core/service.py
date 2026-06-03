"""Service layer: the single API surface used by MCP tools and a future HTTP
layer. Combines live client calls with DB-backed reliability stats.

The live arrival lookup bins the current time with the SAME BinKey used by the
nightly stats job, so reads and writes always agree on the (dow, hour) bin.
"""
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select

from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.reliability import BinKey
from umich_transit.core.storage.db import session_scope
from umich_transit.core.storage.models import ReliabilityStat
from umich_transit.core.storage.queries import (
    find_stops as q_find_stops,
)
from umich_transit.core.storage.queries import (
    get_reliability_stat,
)
from umich_transit.core.storage.queries import (
    list_routes as q_list_routes,
)

CONFIDENCE_THRESHOLD = 50  # sample_count >= -> "high"


class TransitService:
    def __init__(self, *, engine: Engine, mbus: MbusClient) -> None:
        self._engine = engine
        self._mbus = mbus

    def list_routes(self, agency: str | None = None) -> list[dict[str, Any]]:
        with session_scope(self._engine) as session:
            return [
                {
                    "id": r.id, "agency": r.agency,
                    "short_name": r.short_name, "long_name": r.long_name,
                    "color": r.color,
                }
                for r in q_list_routes(session, agency=agency)
            ]

    def find_stops(
        self,
        query: str = "",
        near: tuple[float, float] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        with session_scope(self._engine) as session:
            return [
                {
                    "id": st.id, "agency": st.agency, "name": st.name,
                    "lat": st.lat, "lon": st.lon,
                }
                for st in q_find_stops(session, query=query, near=near, limit=limit)
            ]

    async def get_arrivals(
        self,
        *,
        stop_id: str,
        route_id: str | None = None,
        limit: int = 5,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        moment = now or datetime.now(UTC)
        live = await self._mbus.get_etas(stop_id=stop_id)
        if route_id is not None:
            live = [e for e in live if e.route_id == route_id]

        out: list[dict[str, Any]] = []
        with session_scope(self._engine) as session:
            for e in live[:limit]:
                key = BinKey.from_timestamp(
                    route_id=e.route_id, stop_id=e.stop_id, at=moment,
                )
                stat = get_reliability_stat(
                    session, route_id=e.route_id, stop_id=e.stop_id,
                    dow=key.dow, hour=key.hour,
                )
                if stat is not None:
                    adjusted = e.predicted_arrival_at + timedelta(seconds=stat.mean_delay_s)
                    confidence = "high" if stat.sample_count >= CONFIDENCE_THRESHOLD else "low"
                    on_time: float | None = stat.on_time_pct
                    samples = stat.sample_count
                else:
                    adjusted = e.predicted_arrival_at
                    confidence = "low"
                    on_time = None
                    samples = 0
                out.append({
                    "route_id": e.route_id,
                    "stop_id": e.stop_id,
                    "vehicle_id": e.vehicle_id,
                    "predicted_arrival_at": e.predicted_arrival_at,
                    "adjusted_arrival_at": adjusted,
                    "on_time_pct_at_this_hour": on_time,
                    "sample_size": samples,
                    "confidence": confidence,
                })
        return out

    def route_reliability(
        self,
        *,
        route_id: str,
        day_of_week: int | None = None,
        hour: int | None = None,
    ) -> dict[str, Any]:
        with session_scope(self._engine) as session:
            stmt = select(ReliabilityStat).where(ReliabilityStat.route_id == route_id)
            if day_of_week is not None:
                stmt = stmt.where(ReliabilityStat.dow == day_of_week)
            if hour is not None:
                stmt = stmt.where(ReliabilityStat.hour == hour)
            rows = list(session.execute(stmt).scalars().all())

        if not rows:
            return {"route_id": route_id, "sample_count": 0, "summary": "no data yet"}
        total = sum(r.sample_count for r in rows)
        weighted_mean = sum(r.mean_delay_s * r.sample_count for r in rows) / total
        weighted_on_time = sum(r.on_time_pct * r.sample_count for r in rows) / total
        return {
            "route_id": route_id,
            "sample_count": total,
            "mean_delay_s": weighted_mean,
            "on_time_pct": weighted_on_time,
            "summary": (
                f"{weighted_on_time * 100:.0f}% on-time across {total} arrivals; "
                f"avg delay {weighted_mean:.0f}s"
            ),
        }
