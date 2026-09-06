"""Calendar-day boundary for a group's operational coordinator access."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE


def trip_has_ended(
    *,
    travel_date: date | None,
    return_date: date | None,
    timezone: str | None = DEFAULT_TRIP_TIMEZONE,
    now: datetime | None = None,
) -> bool:
    """Keep access through the final trip day in the group's local timezone.

    An undated group is not implicitly expired. The caller separately decides
    whether undated groups are eligible for *new* coordinator assignments.
    """

    end_date = return_date or travel_date
    if end_date is None:
        return False
    timestamp = now or datetime.now(tz=UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Trip lifecycle checks require a timezone-aware timestamp")
    zone = ZoneInfo((timezone or "").strip() or DEFAULT_TRIP_TIMEZONE)
    return end_date < timestamp.astimezone(zone).date()
