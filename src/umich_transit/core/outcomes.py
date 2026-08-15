"""Build versioned prediction-versus-arrival outcomes from raw observations."""
from dataclasses import dataclass

from sqlalchemy import Engine, delete, select

from umich_transit.core.storage.db import session_scope
from umich_transit.core.storage.models import Arrival, PredictionOutcome
from umich_transit.core.storage.queries import prediction_for_arrival

TARGET_HORIZON_SECONDS = 300
MATCH_TOLERANCE_SECONDS = 90
MATCH_VERSION = "fixed-horizon-v1"


@dataclass(frozen=True)
class OutcomeBuildResult:
    matched: int
    unmatched: int
    rejections: dict[str, int]


def rebuild_prediction_outcomes(engine: Engine) -> OutcomeBuildResult:
    """Rebuild derived fixed-horizon outcomes from predictions and arrivals."""
    matched = unmatched = 0
    rejections: dict[str, int] = {}
    used_prediction_ids: set[int] = set()
    with session_scope(engine) as session:
        session.execute(delete(PredictionOutcome))
        arrivals = list(
            session.execute(select(Arrival).order_by(Arrival.actual_arrival_at)).scalars()
        )
        for arrival in arrivals:
            prediction = prediction_for_arrival(
                session,
                vehicle_id=arrival.vehicle_id,
                route_id=arrival.route_id,
                stop_id=arrival.stop_id,
                arrival_at=arrival.actual_arrival_at,
                target_horizon_seconds=TARGET_HORIZON_SECONDS,
                tolerance_seconds=MATCH_TOLERANCE_SECONDS,
            )
            if prediction is None:
                unmatched += 1
                rejections["no_eligible_prediction"] = (
                    rejections.get("no_eligible_prediction", 0) + 1
                )
                continue
            if prediction.id in used_prediction_ids:
                unmatched += 1
                rejections["prediction_reused"] = rejections.get("prediction_reused", 0) + 1
                continue
            used_prediction_ids.add(prediction.id)
            signed_error = (
                arrival.actual_arrival_at - prediction.predicted_arrival_at
            ).total_seconds()
            session.add(PredictionOutcome(
                prediction_id=prediction.id,
                arrival_id=arrival.id,
                route_id=arrival.route_id,
                stop_id=arrival.stop_id,
                vehicle_id=arrival.vehicle_id,
                prediction_captured_at=prediction.captured_at,
                predicted_arrival_at=prediction.predicted_arrival_at,
                actual_arrival_at=arrival.actual_arrival_at,
                prediction_horizon_s=(
                    arrival.actual_arrival_at - prediction.captured_at
                ).total_seconds(),
                signed_error_s=signed_error,
                absolute_error_s=abs(signed_error),
                detected_via=arrival.detected_via,
                match_version=MATCH_VERSION,
            ))
            matched += 1
    return OutcomeBuildResult(
        matched=matched, unmatched=unmatched, rejections=rejections,
    )
