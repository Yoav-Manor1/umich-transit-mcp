"""Rebuild prediction outcomes, reliability profiles, and holdout reports."""
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, delete, select

from umich_transit.core.accuracy import OutcomeSample, build_profiles, evaluate_accuracy
from umich_transit.core.outcomes import MATCH_VERSION, rebuild_prediction_outcomes
from umich_transit.core.storage.db import session_scope
from umich_transit.core.storage.models import (
    EvaluationReportRow,
    PredictionOutcome,
    ReliabilityProfileRow,
)

MODEL_VERSION = "median-hierarchy-v1"


@dataclass(frozen=True)
class AnalyticsRefreshResult:
    matched_outcomes: int
    profile_count: int
    evaluation_status: str


def refresh_showcase_analytics(engine: Engine) -> AnalyticsRefreshResult:
    outcome_result = rebuild_prediction_outcomes(engine)
    with session_scope(engine) as session:
        outcomes = list(
            session.execute(
                select(PredictionOutcome).order_by(PredictionOutcome.actual_arrival_at)
            ).scalars()
        )
    samples = [
        OutcomeSample(
            route_id=outcome.route_id,
            stop_id=outcome.stop_id,
            actual_arrival_at=outcome.actual_arrival_at,
            signed_error_s=outcome.signed_error_s,
        )
        for outcome in outcomes
    ]
    profiles = build_profiles(samples)
    report = evaluate_accuracy(samples)
    now = datetime.now(UTC)
    with session_scope(engine) as session:
        session.execute(delete(ReliabilityProfileRow))
        session.add_all([
            ReliabilityProfileRow(
                profile_key=_profile_key(profile.scope, profile.route_id,
                                         profile.stop_id, profile.dow, profile.hour),
                scope=profile.scope,
                route_id=profile.route_id,
                stop_id=profile.stop_id,
                dow=profile.dow,
                hour=profile.hour,
                correction_s=profile.correction_s,
                sample_count=profile.sample_count,
                updated_at=now,
            )
            for profile in profiles
        ])
        metrics: dict[str, object] | None = None
        if report.overall is not None:
            metrics = asdict(report.overall)
            metrics["routes"] = {
                route_id: asdict(comparison)
                for route_id, comparison in report.routes.items()
            }
        session.add(EvaluationReportRow(
            generated_at=now,
            status=report.status,
            total_sample_count=report.total_sample_count,
            training_sample_count=report.training_sample_count,
            holdout_sample_count=report.holdout_sample_count,
            match_version=MATCH_VERSION,
            model_version=MODEL_VERSION,
            metrics_json=metrics,
        ))
    return AnalyticsRefreshResult(
        matched_outcomes=outcome_result.matched,
        profile_count=len(profiles),
        evaluation_status=report.status,
    )


def _profile_key(
    scope: str, route_id: str, stop_id: str | None, dow: int | None, hour: int,
) -> str:
    return "|".join((scope, route_id, stop_id or "*", str(dow) if dow is not None else "*",
                     str(hour)))
