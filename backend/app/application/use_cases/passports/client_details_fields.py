"""Authoritative editor descriptors for saved client-provided group details."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.application.use_cases.whatsapp.group_submission_matching import (
    normalize_matching_field_key,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.domain.value_objects.upload_configuration import configuration_for

DIRECT_FIELDS = frozenset(
    {"client_email", "client_phone", "departure_city", "nearest_domestic_airport"}
)
FieldType = Literal["text", "email", "tel", "select"]
FieldDefinition = tuple[str, str, bool, bool, FieldType, tuple[str, ...], int]


@dataclass(frozen=True)
class ClientDetailField:
    key: str
    label: str
    value: str | None
    required: bool = False
    type: Literal["text", "email", "tel", "select"] = "text"
    options: tuple[str, ...] = ()
    max_length: int = 120


def scalar_value(submission: PassportSubmission, key: str) -> str | None:
    if key in DIRECT_FIELDS:
        value = getattr(submission, key)
    else:
        # An explicitly cleared confirmed value must not revive a legacy value.
        sources = (
            submission.confirmed_fields,
            submission.extracted_fields,
            submission.staff_metadata,
        )
        canonical = normalize_matching_field_key(key)
        value = None
        for source in sources:
            matches = [
                raw for raw in (source or {}) if normalize_matching_field_key(raw) == canonical
            ]
            if matches and source is not None:
                value = source[matches[-1]]
                break
    return str(value) if value is not None else None


def client_detail_fields(
    submission: PassportSubmission, group: ClientGroup
) -> list[ClientDetailField]:
    config = configuration_for(group)
    metadata = submission.staff_metadata or {}
    definitions: list[FieldDefinition] = [
        ("client_email", "Email entered by client", True, False, "email", (), 254),
        ("client_phone", "Phone entered by client", True, False, "tel", (), 32),
        (
            "departure_city",
            "Nearest international airport",
            group.nearest_international_airport_enabled or bool(group.departure_cities),
            config.required("departure_city"),
            "select" if group.departure_cities else "text",
            tuple(group.departure_cities or ()),
            120,
        ),
        (
            "nearest_domestic_airport",
            "Nearest domestic airport",
            group.ask_nearest_domestic_airport,
            config.required("nearest_domestic_airport"),
            "text",
            (),
            120,
        ),
        (
            "base_city",
            "Base City",
            group.base_city_enabled,
            config.required("base_city"),
            "text",
            (),
            120,
        ),
        (
            "staff_code",
            "Staff Code",
            group.staff_code_enabled,
            config.required("staff_code"),
            "text",
            (),
            80,
        ),
        (
            "agent_employee_type",
            "Agent / Employee",
            bool(scalar_value(submission, "agent_employee_type")),
            False,
            "select",
            ("agent", "employee"),
            20,
        ),
        (
            "agent_employee_code",
            str(metadata.get("agent_employee_code_label") or config.agent_employee_code_label),
            group.agent_employee_code_enabled,
            config.required("agent_employee_code"),
            "text",
            (),
            80,
        ),
        (
            "designation",
            "Designation",
            group.designation_enabled,
            config.required("designation"),
            "text",
            (),
            160,
        ),
        (
            "agency_dealership_name",
            str(
                metadata.get("agency_dealership_name_label") or config.agency_dealership_name_label
            ),
            group.agency_dealership_name_enabled,
            config.required("agency_dealership_name"),
            "text",
            (),
            200,
        ),
        (
            "meal_preference",
            "Meal Preference",
            group.meal_preference_enabled,
            config.required("meal_preference"),
            "select",
            ("Veg", "Non Veg", "Jain"),
            20,
        ),
    ]
    fields = []
    for key, label, enabled, required, kind, options, maximum in definitions:
        value = scalar_value(submission, str(key))
        if enabled or value:
            fields.append(
                ClientDetailField(
                    key=str(key),
                    label=str(label),
                    value=value,
                    required=bool(enabled and required),
                    type=kind,
                    options=options,
                    max_length=maximum,
                )
            )
    return fields


def custom_detail_fields(
    saved: Sequence[Mapping[str, object]],
    definitions: Sequence[Mapping[str, object]],
    *,
    id_key: str,
) -> list[dict[str, Any]]:
    """Use stable IDs and original labels; retained retired answers remain editable."""
    by_id = {str(item["id"]): item for item in definitions}
    snapshots = {str(item[id_key]): item for item in saved}
    ids = list(snapshots)
    ids.extend(
        str(item["id"])
        for item in definitions
        if item.get("enabled", True) and str(item["id"]) not in snapshots
    )
    result = []
    for item_id in ids:
        definition = by_id.get(item_id, {})
        snapshot = snapshots.get(item_id, {})
        descriptor: dict[str, Any] = {
            id_key: item_id,
            "label": str(snapshot.get("label") or definition.get("label") or "Saved detail"),
            "value": snapshot.get("value"),
            "required": bool(definition.get("enabled", True) and definition.get("required", False)),
            "max_length": 120 if id_key == "question_id" else 500,
        }
        if id_key == "question_id":
            options = definition.get("options")
            descriptor["options"] = list(options) if isinstance(options, list) else []
        result.append(descriptor)
    return result


def client_details_payload(submission: PassportSubmission, group: ClientGroup) -> dict[str, Any]:
    return {
        "updated_at": submission.updated_at,
        "fields": client_detail_fields(submission, group),
        "custom_answers": custom_detail_fields(
            submission.custom_answers, group.custom_questions, id_key="question_id"
        ),
        "custom_detail_answers": custom_detail_fields(
            submission.custom_detail_answers, group.custom_details, id_key="detail_id"
        ),
    }
