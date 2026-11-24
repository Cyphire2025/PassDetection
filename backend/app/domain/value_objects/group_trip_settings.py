"""Shared editable trip-field normalization for group creation and changes."""

from __future__ import annotations

from datetime import date

from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.trip_timezone import normalize_trip_timezone


def normalize_departure_cities(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cities: list[str] = []
    for value in values:
        city = " ".join(str(value).strip().split())
        if not city:
            continue
        key = city.casefold()
        if key in seen:
            continue
        seen.add(key)
        cities.append(city[:120])
    return cities


def normalize_group_trip_settings(
    *,
    name: str,
    travel_date: date | None,
    return_date: date | None,
    timezone: str,
    departure_cities: list[str] | None,
    nearest_international_airport_enabled: bool,
    import_only: bool,
) -> tuple[str, str, list[str]]:
    """Validate shared trip fields before changing the group entity."""
    normalized_name = " ".join(name.strip().split())
    if not normalized_name:
        raise ValidationError("Group name is required.", field="name")
    if travel_date and return_date and return_date < travel_date:
        raise ValidationError(
            "Return date cannot be before the Travel/Departure date.",
            field="return_date",
        )
    try:
        normalized_timezone = normalize_trip_timezone(timezone)
    except ValueError as exc:
        raise ValidationError(str(exc), field="timezone") from exc
    normalized_departure_cities = (
        normalize_departure_cities(departure_cities or [])
        if nearest_international_airport_enabled and not import_only
        else []
    )
    if (
        not import_only
        and nearest_international_airport_enabled
        and not normalized_departure_cities
    ):
        raise ValidationError(
            "Add at least one nearest international airport.",
            field="departure_cities",
        )
    return normalized_name, normalized_timezone, normalized_departure_cities
