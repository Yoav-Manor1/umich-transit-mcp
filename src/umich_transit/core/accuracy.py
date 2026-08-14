"""Transparent reliability profiles and chronological accuracy evaluation."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean, median
from zoneinfo import ZoneInfo

AGENCY_TZ = ZoneInfo("America/Detroit")
HIGH_CONFIDENCE_SAMPLES = 30
MEDIUM_CONFIDENCE_SAMPLES = 20
MAX_CORRECTION_SECONDS = 600.0
MIN_EVALUATION_SAMPLES = 100


@dataclass(frozen=True)
class OutcomeSample:
    route_id: str
    stop_id: str
    actual_arrival_at: datetime
    signed_error_s: float


@dataclass(frozen=True)
class ReliabilityProfile:
    scope: str
    route_id: str
    stop_id: str | None
    dow: int | None
    hour: int
    correction_s: float
    sample_count: int


@dataclass(frozen=True)
class Adjustment:
    correction_s: float
    confidence: str
    scope: str | None
    sample_count: int


@dataclass(frozen=True)
class AccuracyMetrics:
    mean_absolute_error_s: float
    median_absolute_error_s: float
    mean_signed_error_s: float
    within_two_minutes_pct: float


@dataclass(frozen=True)
class AccuracyComparison:
    sample_count: int
    published: AccuracyMetrics
    adjusted: AccuracyMetrics
    classification: str


@dataclass(frozen=True)
class AccuracyReport:
    status: str
    total_sample_count: int
    training_sample_count: int
    holdout_sample_count: int
    overall: AccuracyComparison | None
    routes: dict[str, AccuracyComparison]


def build_profiles(samples: list[OutcomeSample]) -> list[ReliabilityProfile]:
    grouped: dict[tuple[str, str, str | None, int | None, int], list[float]] = (
        defaultdict(list)
    )
    for sample in samples:
        local = _local(sample.actual_arrival_at)
        keys = (
            ("route_stop_dow_hour", sample.route_id, sample.stop_id,
             local.weekday(), local.hour),
            ("route_stop_hour", sample.route_id, sample.stop_id, None, local.hour),
            ("route_dow_hour", sample.route_id, None, local.weekday(), local.hour),
        )
        for key in keys:
            grouped[key].append(sample.signed_error_s)

    profiles: list[ReliabilityProfile] = []
    for (scope, route_id, stop_id, dow, hour), errors in grouped.items():
        correction = max(-MAX_CORRECTION_SECONDS, min(MAX_CORRECTION_SECONDS, median(errors)))
        profiles.append(ReliabilityProfile(
            scope=scope,
            route_id=route_id,
            stop_id=stop_id,
            dow=dow,
            hour=hour,
            correction_s=float(correction),
            sample_count=len(errors),
        ))
    return profiles


def select_adjustment(
    profiles: list[ReliabilityProfile],
    *,
    route_id: str,
    stop_id: str,
    at: datetime,
) -> Adjustment:
    local = _local(at)
    candidates = (
        ("route_stop_dow_hour", stop_id, local.weekday(), HIGH_CONFIDENCE_SAMPLES, "high"),
        ("route_stop_hour", stop_id, None, MEDIUM_CONFIDENCE_SAMPLES, "medium"),
        ("route_dow_hour", None, local.weekday(), MEDIUM_CONFIDENCE_SAMPLES, "medium"),
    )
    for scope, candidate_stop, dow, threshold, confidence in candidates:
        profile = next(
            (
                item for item in profiles
                if item.scope == scope
                and item.route_id == route_id
                and item.stop_id == candidate_stop
                and item.dow == dow
                and item.hour == local.hour
            ),
            None,
        )
        if profile is not None and profile.sample_count >= threshold:
            return Adjustment(
                correction_s=profile.correction_s,
                confidence=confidence,
                scope=profile.scope,
                sample_count=profile.sample_count,
            )
    return Adjustment(correction_s=0, confidence="low", scope=None, sample_count=0)


def evaluate_accuracy(samples: list[OutcomeSample]) -> AccuracyReport:
    ordered = sorted(samples, key=lambda sample: sample.actual_arrival_at)
    if len(ordered) < MIN_EVALUATION_SAMPLES:
        return AccuracyReport(
            status="insufficient_data",
            total_sample_count=len(ordered),
            training_sample_count=0,
            holdout_sample_count=0,
            overall=None,
            routes={},
        )

    split_at = int(len(ordered) * 0.8)
    training = ordered[:split_at]
    holdout = ordered[split_at:]
    profiles = build_profiles(training)
    published_errors = [sample.signed_error_s for sample in holdout]
    adjusted_errors = [
        sample.signed_error_s - select_adjustment(
            profiles,
            route_id=sample.route_id,
            stop_id=sample.stop_id,
            at=sample.actual_arrival_at,
        ).correction_s
        for sample in holdout
    ]
    overall = _comparison(published_errors, adjusted_errors)
    route_errors: dict[str, tuple[list[float], list[float]]] = {}
    for sample, adjusted_error in zip(holdout, adjusted_errors, strict=True):
        published_for_route, adjusted_for_route = route_errors.setdefault(
            sample.route_id, ([], [])
        )
        published_for_route.append(sample.signed_error_s)
        adjusted_for_route.append(adjusted_error)
    routes = {
        route_id: _comparison(route_published, route_adjusted)
        for route_id, (route_published, route_adjusted) in route_errors.items()
        if len(route_published) >= 20
    }
    return AccuracyReport(
        status="ready",
        total_sample_count=len(ordered),
        training_sample_count=len(training),
        holdout_sample_count=len(holdout),
        overall=overall,
        routes=routes,
    )


def _local(at: datetime) -> datetime:
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return at.astimezone(AGENCY_TZ)


def _metrics(errors: list[float]) -> AccuracyMetrics:
    absolute = [abs(error) for error in errors]
    return AccuracyMetrics(
        mean_absolute_error_s=float(mean(absolute)),
        median_absolute_error_s=float(median(absolute)),
        mean_signed_error_s=float(mean(errors)),
        within_two_minutes_pct=sum(1 for error in absolute if error <= 120) / len(errors),
    )


def _comparison(
    published_errors: list[float], adjusted_errors: list[float],
) -> AccuracyComparison:
    published = _metrics(published_errors)
    adjusted = _metrics(adjusted_errors)
    improvement = published.mean_absolute_error_s - adjusted.mean_absolute_error_s
    if improvement >= 1:
        classification = "improved"
    elif improvement <= -1:
        classification = "worsened"
    else:
        classification = "tied"
    return AccuracyComparison(
        sample_count=len(published_errors),
        published=published,
        adjusted=adjusted,
        classification=classification,
    )
