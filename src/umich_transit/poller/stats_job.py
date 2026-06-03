"""Nightly job that recomputes ReliabilityStat rows from arrivals + predictions."""
from collections import defaultdict
from datetime import UTC, datetime

import structlog
from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from umich_transit.core.reliability import (
    BinKey,
    compute_bin_stats,
    delays_from_pairs,
)
from umich_transit.core.storage.db import session_scope
from umich_transit.core.storage.models import Arrival, ReliabilityStat
from umich_transit.core.storage.queries import prediction_for_arrival

logger = structlog.get_logger(__name__)


def recompute_all_bins(
    engine: Engine,
    *,
    lookback_seconds: int,
    on_time_threshold_s: float,
) -> int:
    """Walk all arrivals, match each to its ~5-min-prior prediction, bin, upsert.

    Returns the number of bins written.
    """
    bins: dict[BinKey, list[float]] = defaultdict(list)
    matched = unmatched = 0

    with session_scope(engine) as s:
        arrivals = list(s.execute(select(Arrival)).scalars().all())
        for a in arrivals:
            pred = prediction_for_arrival(
                s,
                vehicle_id=a.vehicle_id,
                stop_id=a.stop_id,
                arrival_at=a.actual_arrival_at,
                lookback_seconds=lookback_seconds,
            )
            if pred is None:
                unmatched += 1
                continue
            matched += 1
            delays = delays_from_pairs(
                [(pred.predicted_arrival_at, a.actual_arrival_at)]
            )
            key = BinKey.from_timestamp(
                route_id=a.route_id, stop_id=a.stop_id, at=a.actual_arrival_at,
            )
            bins[key].extend(delays)

    now = datetime.now(UTC)
    written = 0
    with session_scope(engine) as s:
        for key, delays in bins.items():
            stats = compute_bin_stats(delays, on_time_threshold_s=on_time_threshold_s)
            stmt = sqlite_insert(ReliabilityStat).values(
                route_id=key.route_id, stop_id=key.stop_id,
                dow=key.dow, hour=key.hour,
                on_time_pct=stats.on_time_pct,
                mean_delay_s=stats.mean_delay_s,
                p50_delay_s=stats.p50_delay_s,
                p90_delay_s=stats.p90_delay_s,
                sample_count=stats.sample_count,
                updated_at=now,
            )
            s.execute(stmt.on_conflict_do_update(
                index_elements=[
                    ReliabilityStat.route_id, ReliabilityStat.stop_id,
                    ReliabilityStat.dow, ReliabilityStat.hour,
                ],
                set_={
                    "on_time_pct": stats.on_time_pct,
                    "mean_delay_s": stats.mean_delay_s,
                    "p50_delay_s": stats.p50_delay_s,
                    "p90_delay_s": stats.p90_delay_s,
                    "sample_count": stats.sample_count,
                    "updated_at": now,
                },
            ))
            written += 1

    logger.info("stats_job.done", matched=matched, unmatched=unmatched, bins=written)
    return written
