"""Tests for transparent reliability profiles and holdout evaluation."""
from datetime import UTC, datetime, timedelta

import pytest

from umich_transit.core.accuracy import (
    OutcomeSample,
    build_profiles,
    evaluate_accuracy,
    select_adjustment,
)

BASE = datetime(2026, 1, 5, 13, 0, tzinfo=UTC)


def _sample(
    index: int,
    *,
    error: float,
    route_id: str = "r1",
    stop_id: str = "s1",
) -> OutcomeSample:
    return OutcomeSample(
        route_id=route_id,
        stop_id=stop_id,
        actual_arrival_at=BASE + timedelta(days=7 * index),
        signed_error_s=error,
    )


def test_exact_profile_uses_clamped_median_and_high_confidence():
    samples = [
        OutcomeSample("r1", "s1", BASE, 120)
        for _ in range(29)
    ] + [OutcomeSample("r1", "s1", BASE, 1200)]

    profiles = build_profiles(samples)
    adjustment = select_adjustment(
        profiles, route_id="r1", stop_id="s1", at=samples[-1].actual_arrival_at,
    )

    assert adjustment.confidence == "high"
    assert adjustment.scope == "route_stop_dow_hour"
    assert adjustment.sample_count == 30
    assert adjustment.correction_s == pytest.approx(120)


def test_broader_route_stop_hour_profile_provides_medium_confidence():
    samples = [
        OutcomeSample(
            route_id="r1", stop_id="s1",
            actual_arrival_at=BASE + timedelta(days=i),
            signed_error_s=180,
        )
        for i in range(20)
    ]

    adjustment = select_adjustment(
        build_profiles(samples), route_id="r1", stop_id="s1", at=BASE,
    )

    assert adjustment.confidence == "medium"
    assert adjustment.scope == "route_stop_hour"
    assert adjustment.sample_count == 20
    assert adjustment.correction_s == pytest.approx(180)


def test_insufficient_history_returns_original_prediction():
    samples = [_sample(i, error=300) for i in range(5)]

    adjustment = select_adjustment(
        build_profiles(samples), route_id="r1", stop_id="s1", at=BASE,
    )

    assert adjustment.confidence == "low"
    assert adjustment.scope is None
    assert adjustment.correction_s == 0


def test_evaluation_requires_one_hundred_outcomes():
    report = evaluate_accuracy([_sample(i, error=60) for i in range(99)])

    assert report.status == "insufficient_data"
    assert report.total_sample_count == 99
    assert report.overall is None


def test_evaluation_trains_on_oldest_eighty_percent():
    training = [_sample(i, error=60) for i in range(80)]
    holdout = [_sample(i + 80, error=60) for i in range(20)]

    report = evaluate_accuracy(training + holdout)

    assert report.status == "ready"
    assert report.training_sample_count == 80
    assert report.holdout_sample_count == 20
    assert report.overall is not None
    assert report.overall.published.mean_absolute_error_s == pytest.approx(60)
    assert report.overall.adjusted.mean_absolute_error_s == pytest.approx(0)
    assert report.overall.sample_count == 20
    assert report.overall.classification == "improved"
    assert report.routes["r1"].classification == "improved"


def test_holdout_only_route_cannot_leak_into_training_profiles():
    training = [_sample(i, error=0, route_id="r1") for i in range(80)]
    holdout = [_sample(i + 80, error=600, route_id="r2") for i in range(20)]

    report = evaluate_accuracy(training + holdout)

    assert report.overall is not None
    assert report.overall.published.mean_absolute_error_s == pytest.approx(600)
    assert report.overall.adjusted.mean_absolute_error_s == pytest.approx(600)
    assert report.overall.classification == "tied"
