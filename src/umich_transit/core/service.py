"""Shared service API for live arrivals, reliability, and held-out accuracy."""
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select

from umich_transit.core.accuracy import ReliabilityProfile, select_adjustment
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.planner import TripPlanner
from umich_transit.core.storage.db import session_scope
from umich_transit.core.storage.models import (
    EvaluationReportRow,
    ReliabilityProfileRow,
    ReliabilityStat,
    RouteStop,
)
from umich_transit.core.storage.queries import find_stops as q_find_stops
from umich_transit.core.storage.queries import list_routes as q_list_routes

STALE_AFTER_SECONDS = 300


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
                rows = list(session.execute(
                    select(ReliabilityProfileRow).where(
                        ReliabilityProfileRow.route_id == e.route_id
                    )
                ).scalars())
                profiles = [
                    ReliabilityProfile(
                        scope=row.scope,
                        route_id=row.route_id,
                        stop_id=row.stop_id,
                        dow=row.dow,
                        hour=row.hour,
                        correction_s=row.correction_s,
                        sample_count=row.sample_count,
                    )
                    for row in rows
                ]
                adjustment = select_adjustment(
                    profiles,
                    route_id=e.route_id,
                    stop_id=e.stop_id,
                    at=e.predicted_arrival_at,
                )
                adjusted = e.predicted_arrival_at + timedelta(
                    seconds=adjustment.correction_s
                )
                data_age_s = max(0.0, (moment - e.captured_at).total_seconds())
                out.append({
                    "route_id": e.route_id,
                    "stop_id": e.stop_id,
                    "vehicle_id": e.vehicle_id,
                    "predicted_arrival_at": e.predicted_arrival_at,
                    "adjusted_arrival_at": adjusted,
                    "on_time_pct_at_this_hour": None,
                    "sample_size": adjustment.sample_count,
                    "confidence": adjustment.confidence,
                    "correction_s": adjustment.correction_s,
                    "adjustment_scope": adjustment.scope,
                    "adjustment_reason": _adjustment_reason(adjustment),
                    "data_age_s": data_age_s,
                    "is_stale": data_age_s > STALE_AFTER_SECONDS,
                })
        return out

    def prediction_accuracy(self, route_id: str | None = None) -> dict[str, Any]:
        with session_scope(self._engine) as session:
            report = session.execute(
                select(EvaluationReportRow)
                .order_by(EvaluationReportRow.generated_at.desc(), EvaluationReportRow.id.desc())
                .limit(1)
            ).scalar_one_or_none()
        if report is None:
            return {
                "status": "insufficient_data",
                "summary": "No evaluation report yet. Run the analytics refresh first.",
            }
        metrics = report.metrics_json
        if route_id is not None:
            routes = metrics.get("routes") if metrics is not None else None
            route_metrics = routes.get(route_id) if isinstance(routes, dict) else None
            if not isinstance(route_metrics, dict):
                return {
                    "status": "insufficient_data",
                    "route_id": route_id,
                    "summary": "This route does not have 20 held-out arrivals yet.",
                }
            metrics = route_metrics
        return {
            "status": report.status,
            "route_id": route_id,
            "generated_at": report.generated_at,
            "total_sample_count": report.total_sample_count,
            "training_sample_count": report.training_sample_count,
            "holdout_sample_count": report.holdout_sample_count,
            "match_version": report.match_version,
            "model_version": report.model_version,
            "metrics": metrics,
        }

    async def plan_trip(
        self, *, from_stop_id: str, to_stop_id: str,
    ) -> dict[str, Any]:
        with session_scope(self._engine) as session:
            rs_rows = list(session.execute(select(RouteStop)).scalars().all())
        route_stops: dict[str, list[str]] = {}
        stop_to_routes: dict[str, list[str]] = {}
        for rs in rs_rows:
            route_stops.setdefault(rs.route_id, []).append(rs.stop_id)
            stop_to_routes.setdefault(rs.stop_id, []).append(rs.route_id)

        upcoming = await self.get_arrivals(stop_id=from_stop_id)
        planner = TripPlanner(route_stops=route_stops, stop_to_routes=stop_to_routes)
        plan = planner.plan(
            from_stop_id=from_stop_id, to_stop_id=to_stop_id,
            upcoming_arrivals=upcoming,
        )
        if plan is None:
            return {"summary": "No same-route trip available.", "plan": None}
        seg = plan.segments[0]
        return {
            "summary": (
                f"Take route {seg.route_id} (vehicle {seg.vehicle_id}) "
                f"from {seg.from_stop_id} to {seg.to_stop_id}"
            ),
            "plan": {
                "segments": [{
                    "mode": seg.mode,
                    "route_id": seg.route_id,
                    "vehicle_id": seg.vehicle_id,
                    "from_stop_id": seg.from_stop_id,
                    "to_stop_id": seg.to_stop_id,
                    "board_at": seg.board_at.isoformat(),
                    "adjusted_arrival_at": seg.adjusted_arrival_at.isoformat(),
                }],
            },
        }

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


def _adjustment_reason(adjustment: Any) -> str:
    if adjustment.confidence == "low":
        return "There is not enough history to adjust this prediction."
    minutes = abs(adjustment.correction_s) / 60
    timing = "late" if adjustment.correction_s >= 0 else "early"
    return (
        f"This route is typically {minutes:g} minutes {timing} here around this hour "
        f"({adjustment.sample_count} historical arrivals)."
    )
