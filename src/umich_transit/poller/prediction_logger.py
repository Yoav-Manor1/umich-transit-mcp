"""Insert Prediction rows from a batch of ETA records.

Skips ETAs whose route or stop is unknown (not yet seeded). This avoids
foreign-key errors during early runs.
"""
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from umich_transit.core.clients.base import EtaRecord
from umich_transit.core.storage.models import Prediction, Route, Stop

logger = structlog.get_logger(__name__)


def log_predictions(session: Session, etas: list[EtaRecord]) -> int:
    """Insert one Prediction per ETA. Returns count inserted."""
    if not etas:
        return 0
    known_routes = set(session.execute(select(Route.id)).scalars().all())
    known_stops = set(session.execute(select(Stop.id)).scalars().all())

    rows: list[Prediction] = []
    skipped = 0
    for e in etas:
        if e.route_id not in known_routes or e.stop_id not in known_stops:
            skipped += 1
            continue
        rows.append(Prediction(
            route_id=e.route_id,
            stop_id=e.stop_id,
            vehicle_id=e.vehicle_id,
            predicted_arrival_at=e.predicted_arrival_at,
            captured_at=e.captured_at,
        ))
    if rows:
        session.add_all(rows)
    if skipped:
        logger.warning("log_predictions.skipped_unknown", count=skipped)
    return len(rows)
