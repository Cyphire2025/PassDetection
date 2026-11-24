"""Resolve collected fields and unique imported values without identity-policy changes."""

from __future__ import annotations

from app.application.use_cases.whatsapp.group_submission_matching import SubmissionMatchRow
from app.infrastructure.database.models import PassportSubmissionModel

from .priority_field_policy import _clean_value, normalize_imported_field_key


def _submission_field_values(
    passenger: PassportSubmissionModel,
    fields: list[dict[str, str]],
) -> dict[str, str | None]:
    passport_fields = passenger.confirmed_fields or passenger.extracted_fields or {}
    staff_metadata = passenger.staff_metadata or {}
    normalized_staff_metadata = {
        normalize_imported_field_key(raw_key): raw_value
        for raw_key, raw_value in staff_metadata.items()
    }
    custom_answers = {
        f"custom:{answer.get('question_id')}": _clean_value(answer.get("value"))
        for answer in passenger.custom_answers or []
        if answer.get("question_id")
    }
    custom_details = {
        f"custom_detail:{answer.get('detail_id')}": _clean_value(answer.get("value"))
        for answer in passenger.custom_detail_answers or []
        if answer.get("detail_id")
    }
    family_group = _clean_value(passenger.family_head_name) or (
        str(passenger.family_group_id) if passenger.family_group_id else None
    )
    standard_values: dict[str, object] = {
        "field:client_phone": passenger.client_phone,
        "field:client_email": passenger.client_email,
        "field:nationality": passport_fields.get("nationality"),
        "field:submission_mode": passenger.submission_mode.replace("_", " ").title(),
        "field:family_relation": passenger.family_relation,
        "field:family_group": family_group,
        "field:agency_dealership_name": (
            passport_fields.get("agency_dealership_name")
            or staff_metadata.get("agency_dealership_name")
        ),
        "field:base_city": passport_fields.get("base_city") or staff_metadata.get("base_city"),
        "field:nearest_domestic_airport": passenger.nearest_domestic_airport,
        "field:departure_city": passenger.departure_city,
        "field:meal_preference": (
            passport_fields.get("meal_preference") or staff_metadata.get("meal_preference")
        ),
        "field:designation": (
            passport_fields.get("designation") or staff_metadata.get("designation")
        ),
        "field:qualifier_relation": (
            passenger.qualifier_relation_label if passenger.qualifier_enabled_snapshot else None
        ),
    }
    values: dict[str, str | None] = {}
    for field in fields:
        key = field["key"]
        if key.startswith("custom_detail:"):
            values[key] = custom_details.get(key)
        elif key.startswith("custom:"):
            values[key] = custom_answers.get(key)
        elif key.startswith("metadata:"):
            values[key] = _clean_value(normalized_staff_metadata.get(key.removeprefix("metadata:")))
        elif key.startswith("field:"):
            values[key] = _clean_value(standard_values.get(key))
    return values


def _recipient_value(row: SubmissionMatchRow, normalized_key: str) -> str | None:
    """Compatibility single-field projection using the canonical batched resolver."""
    return _recipient_values(row, [normalized_key])[normalized_key]


def _recipient_values(
    row: SubmissionMatchRow,
    normalized_keys: list[str],
) -> dict[str, str | None]:
    """Scan each source header once; retain one value or an ambiguity marker."""
    requested = frozenset(normalized_keys)
    values: dict[str, tuple[str, str] | None] = {}
    for field_set in sorted(row.recipient_fields, key=lambda item: str(item.recipient_id)):
        for raw_key, raw_value in field_set.fields.items():
            normalized = normalize_imported_field_key(raw_key)
            if normalized not in requested:
                continue
            current = values.get(normalized)
            if normalized in values and current is None:
                continue
            cleaned = _clean_value(raw_value)
            if not cleaned:
                continue
            folded = cleaned.casefold()
            if current is None:
                values[normalized] = (folded, cleaned)
            elif current[0] != folded:
                values[normalized] = None
    return {
        normalized: value[1] if (value := values.get(normalized)) is not None else None
        for normalized in normalized_keys
    }
