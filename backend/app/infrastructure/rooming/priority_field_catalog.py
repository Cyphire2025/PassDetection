"""Bounded rooming field descriptors from collected and imported roster data."""

from __future__ import annotations

from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel

from .priority_field_policy import (
    MAX_ROOMING_FIELD_KEY_LENGTH,
    MAX_ROOMING_METADATA_FIELDS,
    _clean_value,
    _is_unavailable_priority,
    normalize_imported_field_key,
)


def _base_field_definitions(group: ClientGroupModel) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = [
        {"key": "field:client_phone", "label": "Phone Number", "source": "contact"},
        {"key": "field:client_email", "label": "Email ID", "source": "contact"},
        {"key": "field:nationality", "label": "Nationality", "source": "passport"},
        {"key": "field:submission_mode", "label": "Submission Mode", "source": "submission"},
        {"key": "field:family_relation", "label": "Family Relation", "source": "submission"},
        {"key": "field:family_group", "label": "Family / Couple", "source": "submission"},
    ]
    optional = (
        (
            group.agency_dealership_name_enabled,
            "field:agency_dealership_name",
            "Agency/Dealership Name",
        ),
        (group.base_city_enabled, "field:base_city", "Base City"),
        (
            group.ask_nearest_domestic_airport,
            "field:nearest_domestic_airport",
            "Domestic Airport",
        ),
        (
            group.nearest_international_airport_enabled,
            "field:departure_city",
            "International Airport",
        ),
        (group.meal_preference_enabled, "field:meal_preference", "Meal Preference"),
        (group.designation_enabled, "field:designation", "Designation"),
        (
            group.relation_with_qualifier_enabled,
            "field:qualifier_relation",
            "Relation with Qualifier",
        ),
    )
    fields.extend(
        {"key": key, "label": label, "source": "group_field"}
        for enabled, key, label in optional
        if enabled
    )
    for question in group.custom_questions or []:
        label = _clean_value(question.get("label"))
        if (
            question.get("enabled")
            and question.get("id")
            and label
            and not _is_unavailable_priority(label)
        ):
            fields.append(
                {
                    "key": f"custom:{question['id']}",
                    "label": label,
                    "source": "custom_question",
                }
            )
    for detail in group.custom_details or []:
        label = _clean_value(detail.get("label"))
        if (
            detail.get("enabled")
            and detail.get("id")
            and label
            and not _is_unavailable_priority(label)
        ):
            fields.append(
                {
                    "key": f"custom_detail:{detail['id']}",
                    "label": label,
                    "source": "custom_detail",
                }
            )
    return fields


def _humanize_imported_field_label(normalized_key: str) -> str:
    abbreviations = {"id": "ID", "qr": "QR", "vip": "VIP"}
    return " ".join(
        abbreviations.get(part, part.capitalize()) for part in normalized_key.split("_") if part
    )


def _metadata_field_definitions(
    passengers: list[PassportSubmissionModel],
) -> list[dict[str, str]]:
    """Return a deterministic, bounded catalog of safe imported columns."""

    normalized_keys: set[str] = set()
    for passenger in passengers:
        for raw_key in passenger.staff_metadata or {}:
            normalized = normalize_imported_field_key(raw_key)
            field_key = f"metadata:{normalized}"
            if (
                _is_unavailable_priority(normalized)
                or len(field_key) > MAX_ROOMING_FIELD_KEY_LENGTH
            ):
                continue
            normalized_keys.add(normalized)
    return [
        {
            "key": f"metadata:{normalized}",
            "label": _humanize_imported_field_label(normalized),
            "source": "imported_excel",
        }
        for normalized in sorted(normalized_keys)[:MAX_ROOMING_METADATA_FIELDS]
    ]


def _deduplicate_labels(fields: list[dict[str, str]]) -> list[dict[str, str]]:
    used: set[str] = set()
    result: list[dict[str, str]] = []
    for field in fields:
        label = _clean_value(field["label"])
        if not label:
            continue
        candidate = label[:120]
        suffix_index = 1
        while candidate.casefold() in used:
            source = field["source"].replace("_", " ").title()
            suffix = f" ({source})" if suffix_index == 1 else f" ({source} {suffix_index})"
            candidate = f"{label[: max(1, 120 - len(suffix))]}{suffix}"
            suffix_index += 1
        used.add(candidate.casefold())
        result.append({**field, "label": candidate})
    return result
