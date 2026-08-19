"""Canonical trip-timezone policy shared by domain and presentation layers."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TRIP_TIMEZONE = "Asia/Kolkata"
MAX_TRIP_TIMEZONE_LENGTH = 64


def normalize_trip_timezone(value: str) -> str:
    """Return a validated IANA timezone identifier or raise ``ValueError``.

    The identifier is stored rather than a numeric UTC offset so future and
    historical daylight-saving transitions remain source-verifiable. Alias
    identifiers present in the installed IANA database remain valid inputs;
    no lossy offset or city-name guessing is performed.
    """

    if not isinstance(value, str):
        raise ValueError("Trip timezone must be an IANA timezone identifier")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_TRIP_TIMEZONE_LENGTH:
        raise ValueError("Trip timezone must be between 1 and 64 characters")
    try:
        ZoneInfo(normalized)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Trip timezone must be a valid IANA timezone identifier") from exc
    return normalized
