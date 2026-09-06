from datetime import UTC, date, datetime

import pytest

from app.domain.value_objects.trip_lifecycle import trip_has_ended


@pytest.mark.parametrize(
    ("now", "ended"),
    [
        (datetime(2026, 9, 5, 18, 29, 59, 999999, tzinfo=UTC), False),
        (datetime(2026, 9, 5, 18, 30, tzinfo=UTC), True),
    ],
)
def test_trip_expires_only_after_the_full_local_return_day(now: datetime, ended: bool) -> None:
    assert (
        trip_has_ended(travel_date=date(2026, 9, 1), return_date=date(2026, 9, 5), now=now) is ended
    )


@pytest.mark.parametrize("timezone", [None, "", "Asia/Kolkata"])
def test_departure_is_fallback_when_return_is_missing(timezone: str | None) -> None:
    assert trip_has_ended(
        travel_date=date(2026, 9, 5),
        return_date=None,
        timezone=timezone,
        now=datetime(2026, 9, 5, 18, 30, tzinfo=UTC),
    )


def test_in_progress_trip_keeps_access_until_return_date() -> None:
    assert not trip_has_ended(
        travel_date=date(2026, 8, 30),
        return_date=date(2026, 9, 8),
        now=datetime(2026, 9, 6, tzinfo=UTC),
    )


def test_undated_group_is_not_implicitly_expired() -> None:
    assert not trip_has_ended(
        travel_date=None, return_date=None, now=datetime(2026, 9, 6, tzinfo=UTC)
    )


@pytest.mark.parametrize(
    ("timezone", "now", "ended"),
    [
        ("Pacific/Kiritimati", datetime(2026, 9, 5, 10, tzinfo=UTC), True),
        ("America/Los_Angeles", datetime(2026, 9, 6, 6, 59, tzinfo=UTC), False),
        ("America/Los_Angeles", datetime(2026, 9, 6, 7, tzinfo=UTC), True),
        # DST has ended before the local end of 1 November: midnight is 08:00Z.
        ("America/Los_Angeles", datetime(2026, 11, 2, 7, 59, tzinfo=UTC), False),
        ("America/Los_Angeles", datetime(2026, 11, 2, 8, tzinfo=UTC), True),
    ],
)
def test_canonical_timezone_and_dst_control_the_boundary(
    timezone: str,
    now: datetime,
    ended: bool,
) -> None:
    end_date = date(2026, 11, 1) if now.month == 11 else date(2026, 9, 5)
    assert (
        trip_has_ended(travel_date=None, return_date=end_date, timezone=timezone, now=now) is ended
    )


def test_naive_timestamp_is_rejected_instead_of_using_host_timezone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        trip_has_ended(travel_date=date(2026, 9, 5), return_date=None, now=datetime(2026, 9, 6))
