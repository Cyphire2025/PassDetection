"""Bounded group choice and broadcast-link input normalization."""

from __future__ import annotations

import re
import uuid
from typing import cast

from app.domain.value_objects.group_trip_settings import (
    normalize_departure_cities as _canonical_departure_cities,
)


def validated_text_choices(value: object, label: str) -> list[str]:
    """Enforce declared JSON array bounds before deduplication or text cleanup."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of text choices.")
    if len(value) > 50:
        raise ValueError(f"{label} must contain at most 50 choices.")
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} choices must be text.")
    return cast(list[str], value)


def _normalize_departure_cities(values: list[str] | None) -> list[str]:
    return _canonical_departure_cities(validated_text_choices(values, "Departure airports"))


def _normalize_broadcast_group_ids(
    values: list[uuid.UUID] | None,
) -> list[uuid.UUID]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("WhatsApp broadcast ids must be a list.")
    if len(values) > 50:
        raise ValueError("Select at most 50 WhatsApp broadcasts.")
    if any(not isinstance(value, (str, uuid.UUID)) for value in values):
        raise ValueError("WhatsApp broadcast ids must be UUIDs.")
    return list(dict.fromkeys(values))


def _normalize_matching_fields_by_broadcast(
    value: object,
) -> dict[uuid.UUID, list[str]] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Matching fields must be keyed by WhatsApp broadcast id")
    if len(value) > 50:
        raise ValueError("Configure matching fields for at most 50 broadcasts")
    normalized: dict[uuid.UUID, list[str]] = {}
    for raw_broadcast_id, raw_fields in value.items():
        try:
            broadcast_id = uuid.UUID(str(raw_broadcast_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Matching fields require valid WhatsApp broadcast ids") from exc
        if not isinstance(raw_fields, list):
            raise ValueError("Each WhatsApp broadcast requires a list of matching fields")
        fields: list[str] = []
        for raw_field in raw_fields:
            if not isinstance(raw_field, str):
                raise ValueError("Matching field keys must be text")
            key = re.sub(
                r"_+",
                "_",
                re.sub(r"[^a-z0-9]+", "_", raw_field.strip().casefold()),
            ).strip("_")
            if len(key) > 64:
                raise ValueError("Matching field keys must be 64 characters or fewer")
            if key and key not in fields:
                fields.append(key)
        if not fields:
            raise ValueError("Select at least one matching field for each broadcast")
        if len(fields) > 32:
            raise ValueError("Select at most 32 matching fields for each broadcast")
        normalized[broadcast_id] = fields
    return normalized
