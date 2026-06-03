"""Tests for the reliability stats engine."""
from datetime import UTC, datetime

import pytest

from umich_transit.core.reliability import (
    BinKey,
    compute_bin_stats,
    delays_from_pairs,
)


def test_delays_from_pairs_signed_in_seconds():
    pairs = [
        (datetime(2026, 5, 1, 8, 0, tzinfo=UTC),
         datetime(2026, 5, 1, 8, 2, tzinfo=UTC)),  # 2 min late = +120
        (datetime(2026, 5, 1, 8, 5, tzinfo=UTC),
         datetime(2026, 5, 1, 8, 4, tzinfo=UTC)),  # 1 min early = -60
    ]
    delays = delays_from_pairs(pairs)
    assert delays == [120.0, -60.0]


def test_compute_bin_stats_basic():
    delays = [-60, 0, 60, 120, 180, 240, 300, 360, 420, 480]  # 10 samples
    s = compute_bin_stats(delays, on_time_threshold_s=120)
    assert s.sample_count == 10
    assert s.mean_delay_s == pytest.approx(210.0)
    # On-time = |delay| <= 120 -> delays -60, 0, 60, 120 -> 4 of 10
    assert s.on_time_pct == pytest.approx(0.4)
    assert s.p50_delay_s == pytest.approx(210.0, abs=1)  # median, linear interp
    assert s.p90_delay_s == pytest.approx(426.0, abs=1)  # 420*0.9 + 480*0.1


def test_compute_bin_stats_handles_single_sample():
    s = compute_bin_stats([120.0], on_time_threshold_s=120)
    assert s.sample_count == 1
    assert s.mean_delay_s == 120.0
    assert s.p50_delay_s == 120.0
    assert s.p90_delay_s == 120.0
    assert s.on_time_pct == 1.0


def test_compute_bin_stats_rejects_empty():
    with pytest.raises(ValueError):
        compute_bin_stats([], on_time_threshold_s=120)


def test_bin_key_uses_local_time():
    # 14:30 UTC on Fri May 1 2026 is 10:30 EDT (UTC-4) -> hour 10, still Friday
    ts = datetime(2026, 5, 1, 14, 30, tzinfo=UTC)
    key = BinKey.from_timestamp(route_id="r1", stop_id="s1", at=ts)
    assert key.dow == 4 and key.hour == 10
    assert key.route_id == "r1"


def test_bin_key_evening_rolls_to_local_day():
    # 01:30 UTC Sat is 21:30 EDT Fri -> dow=4 (Friday), hour=21
    ts = datetime(2026, 5, 2, 1, 30, tzinfo=UTC)
    key = BinKey.from_timestamp(route_id="r1", stop_id="s1", at=ts)
    assert key.dow == 4 and key.hour == 21


def test_bin_key_naive_treated_as_utc():
    naive = datetime(2026, 5, 1, 14, 30)  # no tzinfo
    key = BinKey.from_timestamp(route_id="r1", stop_id="s1", at=naive)
    assert key.hour == 10  # treated as UTC then localized
