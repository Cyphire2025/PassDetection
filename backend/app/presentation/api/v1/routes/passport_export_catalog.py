"""Stable selectable supplemental export catalogs and collision-safe merging."""

from __future__ import annotations

import uuid

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.infrastructure.export.passport_excel_exporter import (
    PassportExcelExporter,
)
from app.infrastructure.export.passport_excel_phone_columns import is_phone_export_field
from app.presentation.api.v1.routes.passport_export_recipient_values import (
    _WHATSAPP_EMAIL_IMPORTED_KEYS,
    _WHATSAPP_PHONE_IMPORTED_KEYS,
    _normalized_imported_field_key,
    _recipient_export_value,
)

_WHATSAPP_SOURCE_METADATA_KEYS = {
    "row_number",
    "sheet_name",
    "source_file",
    "source_order",
    "source_row",
    "source_sheet",
}

_FIXED_IMPORTED_EXPORT_KEYS = {
    "name",
    "full_name",
    "client_name",
    "passenger_name",
    "recipient_name",
    "staff_name",
    "employee_name",
    "given_names",
    "given_name",
    "first_name",
    "surname",
    "last_name",
    "family_name",
    *_WHATSAPP_EMAIL_IMPORTED_KEYS,
    *_WHATSAPP_PHONE_IMPORTED_KEYS,
    "passport_number",
    "passport_no",
    "passport",
    "nationality",
    "place_of_issue",
    "issue_place",
    "date_of_birth",
    "dob",
    "birth_date",
    "date_of_issue",
    "issue_date",
    "date_of_expiry",
    "expiry_date",
    "expiration_date",
    "sex",
    "gender",
    "nearest_international_airport",
    "international_airport",
    "departure_city",
    "nearest_domestic_airport",
    "domestic_airport",
    "base_city",
    "staff_code",
    "staffcode",
    "staff_id",
    "agent_employee_code",
    "agent_code",
    "employee_code",
    "meal_preference",
    "meal",
    "food_preference",
    "relation_with_qualifier",
    "qualifier_relation",
    "relation",
    "designation",
    "agency_dealership_name",
    "agency_name",
    "dealership_name",
    *_WHATSAPP_SOURCE_METADATA_KEYS,
}

_ZONE_IMPORTED_KEYS = {"zone_name", "zonename", "zone"}


def _export_field_catalog(
    group: ClientGroup,
    rows: list[SubmissionMatchRow],
    submissions: list[PassportSubmission] | None = None,
) -> list[dict[str, str | bool]]:
    """List selectable supplemental columns with stable keys and labels."""

    used_labels = {str(header).casefold() for header in PassportExcelExporter.HEADERS}

    def unique_label(label: str, source_label: str) -> str:
        candidate = label[:120]
        suffix_index = 1
        while candidate.casefold() in used_labels:
            suffix = (
                f" ({source_label})" if suffix_index == 1 else f" ({source_label} {suffix_index})"
            )
            candidate = f"{label[: max(1, 120 - len(suffix))]}{suffix}"
            suffix_index += 1
        used_labels.add(candidate.casefold())
        return candidate

    imported_labels: dict[str, str] = {}
    for row in rows:
        for field_set in row.recipient_fields:
            for raw_key in field_set.fields:
                normalized = _normalized_imported_field_key(str(raw_key))
                if (
                    not normalized
                    or normalized in _FIXED_IMPORTED_EXPORT_KEYS
                    or is_phone_export_field(normalized, str(raw_key))
                ):
                    continue
                if normalized in _ZONE_IMPORTED_KEYS:
                    imported_labels["zone_name"] = "Zone Name"
                    continue
                imported_labels.setdefault(
                    normalized,
                    " ".join(str(raw_key).strip().split())[:120],
                )

    fields: list[dict[str, str | bool]] = []
    for normalized, label in imported_labels.items():
        key = "zone_name" if normalized == "zone_name" else f"whatsapp:{normalized}"
        fields.append(
            {
                "key": key,
                "label": ("Zone Name" if key == "zone_name" else unique_label(label, "WhatsApp")),
                "source": "whatsapp",
                "selected_by_default": key == "zone_name",
            }
        )
    return sorted(
        fields,
        key=lambda field: (
            field["key"] != "zone_name",
            str(field["label"]).casefold(),
            str(field["key"]),
        ),
    )


def _export_agency_match_field_catalog(
    group: ClientGroup,
    rows: list[SubmissionMatchRow],
) -> list[dict[str, str | bool]]:
    """List every user-imported WhatsApp field that can identify an agency."""

    if not group.agency_dealership_name_enabled:
        return []

    imported_labels: dict[str, str] = {}
    for row in rows:
        for field_set in row.recipient_fields:
            for raw_key in field_set.fields:
                normalized = _normalized_imported_field_key(str(raw_key))
                if not normalized or normalized in _WHATSAPP_SOURCE_METADATA_KEYS:
                    continue
                imported_labels.setdefault(
                    normalized,
                    " ".join(str(raw_key).strip().split())[:120],
                )

    return [
        {
            "key": f"whatsapp:{normalized}",
            "label": label,
            "source": "whatsapp",
            "selected_by_default": False,
        }
        for normalized, label in sorted(
            imported_labels.items(),
            key=lambda item: (item[1].casefold(), item[0]),
        )
    ]


def _agency_match_export_field(
    match_field: dict[str, str | bool],
) -> dict[str, str | bool]:
    """Expose the selected match value automatically without duplicating its picker."""

    label = " ".join(str(match_field["label"]).strip().split()) or "Match Value"
    old_label = label if label.casefold().startswith("old ") else f"Old {label}"
    return {
        "key": str(match_field["key"]),
        "label": old_label[:120],
        "source": "whatsapp",
        "selected_by_default": True,
    }


def _merge_export_field_catalogs(
    catalogs: list[list[dict[str, str | bool]]],
) -> list[dict[str, str | bool]]:
    """Place fields shared by every group before group-specific fields."""

    if not catalogs:
        return []

    keyed_catalogs = [{str(field["key"]): field for field in catalog} for catalog in catalogs]
    common_keys = set(keyed_catalogs[0])
    for keyed_catalog in keyed_catalogs[1:]:
        common_keys.intersection_update(keyed_catalog)

    selected_by_default = {
        key: any(
            bool(keyed_catalog.get(key, {}).get("selected_by_default", False))
            for keyed_catalog in keyed_catalogs
        )
        for key in {key for keyed_catalog in keyed_catalogs for key in keyed_catalog}
    }
    merged: list[dict[str, str | bool]] = []
    seen: set[str] = set()
    used_labels = {str(header).casefold() for header in PassportExcelExporter.HEADERS}

    def append_field(field: dict[str, str | bool]) -> None:
        key = str(field["key"])
        if key in seen:
            return
        label = " ".join(str(field["label"]).strip().split())[:120]
        candidate = label
        suffix_index = 1
        while candidate.casefold() in used_labels:
            suffix = " (WhatsApp)" if suffix_index == 1 else f" (WhatsApp {suffix_index})"
            candidate = f"{label[: max(1, 120 - len(suffix))]}{suffix}"
            suffix_index += 1
        seen.add(key)
        used_labels.add(candidate.casefold())
        merged.append(
            {
                **field,
                "label": candidate,
                "selected_by_default": selected_by_default.get(key, False),
            }
        )

    # Zone has an explicit workbook position immediately after Return Date,
    # even when it exists in only one of the selected broadcasts.
    for keyed_catalog in keyed_catalogs:
        zone_field = keyed_catalog.get("zone_name")
        if zone_field is not None:
            append_field(zone_field)
            break
    for field in catalogs[0]:
        if str(field["key"]) in common_keys and str(field["key"]) != "zone_name":
            append_field(field)
    for catalog in catalogs:
        for field in catalog:
            if str(field["key"]) not in common_keys and str(field["key"]) != "zone_name":
                append_field(field)
    return merged


def _combined_export_field_catalog(
    groups: list[ClientGroup],
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
    submissions: list[PassportSubmission],
) -> list[dict[str, str | bool]]:
    submissions_by_group: dict[uuid.UUID, list[PassportSubmission]] = {}
    for submission in submissions:
        submissions_by_group.setdefault(submission.group_id, []).append(submission)
    return _merge_export_field_catalogs(
        [
            _export_field_catalog(
                group,
                rows_by_group.get(group.id, []),
                submissions_by_group.get(group.id, []),
            )
            for group in groups
        ]
    )


def _export_additional_values(
    submissions: list[PassportSubmission],
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
    selected_fields: list[dict[str, str | bool]],
) -> dict[uuid.UUID, dict[str, str | None]]:
    values: dict[uuid.UUID, dict[str, str | None]] = {
        submission.id: {} for submission in submissions
    }
    selected_whatsapp = [
        field for field in selected_fields if str(field["key"]).startswith("whatsapp:")
    ]
    for rows in rows_by_group.values():
        for row in rows:
            if row.status not in {
                "submitted",
                "multiple_submissions",
                "replacement",
            }:
                continue
            for submission_id in row.submission_ids:
                if submission_id not in values:
                    continue
                for field in selected_whatsapp:
                    normalized = str(field["key"]).removeprefix("whatsapp:")
                    values[submission_id][str(field["key"])] = _recipient_export_value(
                        row,
                        normalized,
                    )

    return values
