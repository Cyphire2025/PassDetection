"""Build pending recipient workbook rows and selected supplemental fields."""

from __future__ import annotations

import uuid
from typing import Any

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
)
from app.domain.entities.entities import ClientGroup
from app.infrastructure.export.passport_excel_exporter import (
    passport_age_group,
)
from app.presentation.api.v1.routes.passport_export_metadata import _group_export_details
from app.presentation.api.v1.routes.passport_export_recipient_values import (
    _WHATSAPP_EMAIL_IMPORTED_KEYS,
    _WHATSAPP_PHONE_IMPORTED_KEYS,
    _recipient_export_value,
    _recipient_old_given_name,
)


def _pending_recipient_export_rows(
    *,
    group: ClientGroup,
    rows: list[SubmissionMatchRow],
    excluded_recipient_ids: frozenset[uuid.UUID] = frozenset(),
    include_name_history: bool = False,
) -> list[dict[str, Any]]:
    details = _group_export_details(group)
    pending_rows: list[dict[str, Any]] = []
    for row in rows:
        if (
            not row.recipient_ids
            or row.status not in {"not_submitted", "needs_review"}
            or any(recipient_id in excluded_recipient_ids for recipient_id in row.recipient_ids)
        ):
            continue
        given_names = _recipient_export_value(
            row,
            "given_names",
            "given_name",
            "first_name",
        )
        surname = _recipient_export_value(
            row,
            "surname",
            "last_name",
            "family_name",
        )
        imported_name = _recipient_export_value(
            row,
            "name",
            "full_name",
            "client_name",
            "passenger_name",
            "recipient_name",
            "staff_name",
            "employee_name",
        )
        recipient_names_by_key = {
            normalized.casefold(): normalized
            for name in row.recipient_names
            if (normalized := " ".join(str(name or "").strip().split()))
        }
        unambiguous_recipient_name = (
            next(iter(recipient_names_by_key.values()))
            if len(recipient_names_by_key) == 1
            else None
        )
        client_name = (
            unambiguous_recipient_name
            or imported_name
            or " ".join(part for part in (given_names, surname) if part)
            or row.normalized_phone
            or "Pending recipient"
        )
        date_of_birth = _recipient_export_value(
            row,
            "date_of_birth",
            "dob",
            "birth_date",
        )
        pending_rows.append(
            {
                "Group": details.get("name") or group.name,
                "Destination": details.get("destination"),
                "Travel/Departure Date": details.get("travel_date"),
                "Return Date": details.get("return_date"),
                "Zone Name": _recipient_export_value(
                    row,
                    "zone_name",
                    "zonename",
                    "zone",
                ),
                "Agency/Dealership Name": _recipient_export_value(
                    row,
                    "agency_dealership_name",
                    "agency_name",
                    "dealership_name",
                ),
                "Designation": _recipient_export_value(row, "designation"),
                "Age Group": passport_age_group(
                    date_of_birth,
                    details.get("travel_date"),
                ),
                "WhatsApp Email": _recipient_export_value(
                    row,
                    *_WHATSAPP_EMAIL_IMPORTED_KEYS,
                ),
                "WhatsApp Phone": (
                    row.normalized_phone
                    or _recipient_export_value(
                        row,
                        *_WHATSAPP_PHONE_IMPORTED_KEYS,
                    )
                ),
                "International Airport": _recipient_export_value(
                    row,
                    "nearest_international_airport",
                    "international_airport",
                    "departure_city",
                ),
                "Domestic Airport": _recipient_export_value(
                    row,
                    "nearest_domestic_airport",
                    "domestic_airport",
                ),
                "Base City": _recipient_export_value(row, "base_city"),
                "Staff Code": _recipient_export_value(
                    row,
                    "staff_code",
                    "staffcode",
                    "employee_code",
                    "staff_id",
                ),
                "Agent/Employee Code": _recipient_export_value(
                    row,
                    "agent_employee_code",
                    "agent_code",
                    "employee_code",
                ),
                "Meal Preference": _recipient_export_value(
                    row,
                    "meal_preference",
                    "meal",
                    "food_preference",
                ),
                "Relation with Qualifier": _recipient_export_value(
                    row,
                    "relation_with_qualifier",
                    "qualifier_relation",
                    "relation",
                ),
                "SURNAME": surname.upper() if surname else None,
                "GIVEN NAME": (given_names.upper() if given_names else client_name.upper()),
                "GENDER": (
                    value.upper()
                    if (value := _recipient_export_value(row, "sex", "gender"))
                    else None
                ),
                "Passport Number": _recipient_export_value(
                    row,
                    "passport_number",
                    "passport_no",
                    "passport",
                ),
                "DOB": date_of_birth,
                "DOI": _recipient_export_value(
                    row,
                    "date_of_issue",
                    "issue_date",
                ),
                "DOE": _recipient_export_value(
                    row,
                    "date_of_expiry",
                    "expiry_date",
                    "expiration_date",
                ),
                "Nationality": _recipient_export_value(row, "nationality"),
                "Place of Issue": _recipient_export_value(
                    row,
                    "place_of_issue",
                    "issue_place",
                ),
            }
        )
        if include_name_history:
            pending_rows[-1].update(
                {
                    "Old Given Name": (
                        old_given_name.upper()
                        if (old_given_name := _recipient_old_given_name(row))
                        else None
                    ),
                    "New Surname": None,
                    "New Given Name": None,
                }
            )
    return pending_rows


def _apply_pending_export_fields(
    pending_rows: list[dict[str, Any]],
    match_rows: list[SubmissionMatchRow],
    selected_fields: list[dict[str, str | bool]],
    *,
    excluded_recipient_ids: frozenset[uuid.UUID] = frozenset(),
) -> None:
    source_rows = [
        row
        for row in match_rows
        if (
            row.recipient_ids
            and row.status in {"not_submitted", "needs_review"}
            and not any(
                recipient_id in excluded_recipient_ids for recipient_id in row.recipient_ids
            )
        )
    ]
    for exported_row, source_row in zip(pending_rows, source_rows, strict=True):
        for field in selected_fields:
            key = str(field["key"])
            if key == "zone_name":
                exported_row[str(field["label"])] = _recipient_export_value(
                    source_row,
                    "zone_name",
                    "zonename",
                    "zone",
                )
            elif key.startswith("whatsapp:"):
                exported_row[str(field["label"])] = _recipient_export_value(
                    source_row,
                    key.removeprefix("whatsapp:"),
                )
