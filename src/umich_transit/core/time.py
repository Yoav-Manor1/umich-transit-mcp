"""Agency-local time handling shared by analytics and clients."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

AGENCY_TIMEZONE = ZoneInfo("America/Detroit")


def to_agency_time(at: datetime) -> datetime:
    """Convert a timestamp to agency-local time, treating naive values as UTC."""
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return at.astimezone(AGENCY_TIMEZONE)
