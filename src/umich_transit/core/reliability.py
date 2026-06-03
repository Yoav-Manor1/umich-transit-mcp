"""Reliability stats engine.

Pure functions over numeric delays; no I/O. The nightly batch job calls these
against query results.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean
from zoneinfo import ZoneInfo

AGENCY_TZ = ZoneInfo("America/Detroit")


@dataclass(frozen=True)
class BinKey:
    route_id: str
    stop_id: str
    dow: int  # 0 = Monday
    hour: int  # 0..23

    @classmethod
    def from_timestamp(cls, *, route_id: str, stop_id: str, at: datetime) -> "BinKey":
        """Bin a timestamp by AGENCY-LOCAL (America/Detroit) day-of-week and hour.

        Naive datetimes are assumed UTC. Localizing here (rather than at call
        sites) guarantees the stats job and the live lookup use identical bins.
        """
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        local = at.astimezone(AGENCY_TZ)
        return cls(route_id=route_id, stop_id=stop_id, dow=local.weekday(), hour=local.hour)


@dataclass(frozen=True)
class BinStats:
    sample_count: int
    mean_delay_s: float
    p50_delay_s: float
    p90_delay_s: float
    on_time_pct: float


def delays_from_pairs(pairs: list[tuple[datetime, datetime]]) -> list[float]:
    """For a list of (predicted, actual) pairs, return signed delay in seconds.

    Positive = bus arrived later than predicted.
    """
    return [(actual - predicted).total_seconds() for predicted, actual in pairs]


def _percentile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolated percentile (0 <= p <= 1). Input must be sorted."""
    if not sorted_values:
        raise ValueError("empty input")
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = p * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def compute_bin_stats(delays: list[float], *, on_time_threshold_s: float) -> BinStats:
    if not delays:
        raise ValueError("compute_bin_stats requires at least one sample")
    sorted_d = sorted(delays)
    on_time = sum(1 for d in delays if abs(d) <= on_time_threshold_s)
    return BinStats(
        sample_count=len(delays),
        mean_delay_s=float(mean(delays)),
        p50_delay_s=_percentile(sorted_d, 0.5),
        p90_delay_s=_percentile(sorted_d, 0.9),
        on_time_pct=on_time / len(delays),
    )
