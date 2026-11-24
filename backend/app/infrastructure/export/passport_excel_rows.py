"""Typed row projection and pending-row rendering hooks shared by passport exports."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from app.application.mobile.passenger_phone_authority import authoritative_submission_phone
from app.domain.entities.entities import PassportSubmission
from app.domain.value_objects.personnel_codes import (
    prefixed_agent_employee_code,
    prefixed_staff_code,
)
from app.infrastructure.export.passport_excel_columns import (
    _PENDING_ROW_FILL,
    _ZONE_SEPARATOR_BLANK_ROWS,
    _ExportColumn,
)
from app.infrastructure.export.passport_excel_phone_columns import VERIFIED_WHATSAPP_HEADER
from app.infrastructure.export.passport_excel_values import (
    _export_cell_value,
    _gender_display_value,
    _nationality_display_value,
    _uppercase,
    passport_age_group,
)


class PassportExcelRows:
    """Preserve actual cls/self overrides while owning row values and ordering."""

    @classmethod
    def _append_pending_rows(
        cls,
        worksheet: Any,
        *,
        after_row: int,
        columns: list[_ExportColumn],
        pending_rows: list[dict[str, Any]],
        group_by_header: str | None,
    ) -> int:
        """Append non-submitters beneath the shared header with durable yellow cells."""

        ordered_rows = sorted(
            pending_rows,
            key=lambda values: cls._pending_row_sort_key(
                values,
                group_by_header=group_by_header,
            ),
        )
        previous_group_key: str | None = None
        has_written_row = False
        row_index = after_row
        for values in ordered_rows:
            group_key = cls._group_value(values, group_by_header).casefold()
            if group_by_header and has_written_row and group_key != previous_group_key:
                for _ in range(_ZONE_SEPARATOR_BLANK_ROWS):
                    worksheet.append([])
                    row_index += 1

            row_values: list[Any] = []
            for column in columns:
                # A roster recipient who has not submitted through the link
                # cannot supply the completed-upload contact column.
                value = (
                    None if column.header == VERIFIED_WHATSAPP_HEADER else values.get(column.header)
                )
                row_values.append(_export_cell_value(column, value))
            worksheet.append(row_values)
            row_index += 1
            for column_index, column in enumerate(columns, start=1):
                cell = worksheet.cell(row=row_index, column=column_index)
                cell.fill = _PENDING_ROW_FILL
                if column.number_format and isinstance(cell.value, (date, datetime)):
                    cell.number_format = column.number_format

            previous_group_key = group_key
            has_written_row = True
        return row_index

    @staticmethod
    def _group_value(
        values: dict[str, Any],
        group_by_header: str | None,
    ) -> str:
        if not group_by_header:
            return ""
        return " ".join(str(values.get(group_by_header) or "").strip().split())

    @classmethod
    def _pending_row_sort_key(
        cls,
        values: dict[str, Any],
        *,
        group_by_header: str | None,
    ) -> tuple[bool, str, str, str, str]:
        group_value = cls._group_value(values, group_by_header)
        client_name = " ".join(
            str(
                values.get("New Given Name")
                or values.get("GIVEN NAME")
                or values.get("Old Given Name")
                or values.get("New Surname")
                or values.get("SURNAME")
                or ""
            )
            .strip()
            .split()
        )
        phone = str(values.get("WhatsApp Phone") or "")
        email = str(values.get("WhatsApp Email") or "")
        return (
            not bool(group_value),
            group_value.casefold(),
            client_name.casefold(),
            phone,
            email.casefold(),
        )

    @staticmethod
    def _zone_name(
        submission: PassportSubmission,
        zone_names: dict[uuid.UUID, str] | None,
    ) -> str:
        value: object
        if zone_names is not None and submission.id in zone_names:
            value = zone_names[submission.id]
        else:
            value = (submission.staff_metadata or {}).get("zone_name")
        return " ".join(str(value or "").strip().split())

    @classmethod
    def _submission_sort_key(
        cls,
        submission: PassportSubmission,
        values: dict[str, Any],
        *,
        group_by_header: str | None,
    ) -> tuple[bool, str, str, str]:
        group_value = cls._group_value(values, group_by_header)
        return (
            not bool(group_value),
            group_value.casefold(),
            submission.client_name.casefold(),
            str(submission.id),
        )

    @classmethod
    def _submission_values(
        cls,
        submission: PassportSubmission,
        *,
        group_name: str,
        details: dict[str, Any],
        zone_names: dict[uuid.UUID, str] | None,
        dynamic_fields: list[dict[str, str]],
        additional_values: dict[uuid.UUID, dict[str, str | None]] | None,
        whatsapp_contacts: dict[
            uuid.UUID,
            dict[str, str | None],
        ]
        | None,
        previous_names: dict[
            uuid.UUID,
            dict[str, str | None],
        ]
        | None,
        ecr_results: dict[uuid.UUID, str] | None = None,
    ) -> dict[str, Any]:
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        staff_metadata = submission.staff_metadata or {}
        whatsapp_contact = (whatsapp_contacts or {}).get(submission.id, {})
        previous_name = (previous_names or {}).get(submission.id, {})
        values: dict[str, Any] = {
            "Group": details.get("name") or group_name,
            "Destination": details.get("destination"),
            "Travel/Departure Date": details.get("travel_date"),
            "Return Date": details.get("return_date"),
            "Agency/Dealership Name": (
                fields.get("agency_dealership_name") or staff_metadata.get("agency_dealership_name")
            ),
            "Base City": fields.get("base_city") or staff_metadata.get("base_city"),
            "Staff Code": prefixed_staff_code(
                fields.get("staff_code") or staff_metadata.get("staff_code")
            ),
            "Agent/Employee Code": prefixed_agent_employee_code(
                fields.get("agent_employee_type") or staff_metadata.get("agent_employee_type"),
                fields.get("agent_employee_code") or staff_metadata.get("agent_employee_code"),
            ),
            "Designation": (fields.get("designation") or staff_metadata.get("designation")),
            "Meal Preference": (
                fields.get("meal_preference") or staff_metadata.get("meal_preference")
            ),
            "Relation with Qualifier": (
                submission.qualifier_relation_label
                if submission.qualifier_enabled_snapshot
                else None
            ),
            "Age Group": passport_age_group(
                fields.get("date_of_birth"),
                details.get("travel_date"),
            ),
            "Domestic Airport": submission.nearest_domestic_airport,
            "WhatsApp Email": whatsapp_contact.get("email"),
            "International Airport": submission.departure_city,
            "SURNAME": _uppercase(fields.get("surname")),
            "GIVEN NAME": _uppercase(fields.get("given_names")),
            "Old Given Name": _uppercase(previous_name.get("given_names")),
            "New Surname": _uppercase(fields.get("surname")),
            "New Given Name": _uppercase(fields.get("given_names")),
            "GENDER": _gender_display_value(fields.get("sex")),
            "Passport Number": fields.get("passport_number"),
            "DOB": fields.get("date_of_birth"),
            "DOI": fields.get("date_of_issue"),
            "DOE": fields.get("date_of_expiry"),
            "Place of Issue": fields.get("place_of_issue"),
            "Nationality": _nationality_display_value(fields.get("nationality")),
            "ECR": cls._ecr_value(submission.id, details, ecr_results),
            "Upload Email": submission.client_email,
            VERIFIED_WHATSAPP_HEADER: authoritative_submission_phone(submission),
        }
        row_metadata = (additional_values or {}).get(submission.id, {})
        custom_answers = {
            f"custom:{answer.get('question_id')}": answer.get("value")
            for answer in getattr(submission, "custom_answers", []) or []
            if answer.get("question_id")
        }
        custom_detail_answers = {
            f"custom_detail:{answer.get('detail_id')}": answer.get("value")
            for answer in getattr(submission, "custom_detail_answers", []) or []
            if answer.get("detail_id")
        }
        for field in dynamic_fields:
            key = str(field["key"])
            if key == "zone_name":
                value = cls._zone_name(submission, zone_names) or None
            elif key.startswith("custom_detail:"):
                value = custom_detail_answers.get(key)
            elif key.startswith("custom:"):
                value = custom_answers.get(key)
            else:
                value = row_metadata.get(key)
            values[field["label"]] = value
        return values

    @staticmethod
    def _ecr_value(
        submission_id: uuid.UUID,
        details: dict[str, Any],
        results: dict[uuid.UUID, str] | None,
    ) -> str | None:
        if not details.get("passport_ecr_enabled"):
            return None
        result = (results or {}).get(submission_id, "PENDING")
        if result == "NOT_ENABLED":
            return None
        # No image or an unresolved classification cannot prove absence.
        return result if result in {"ECR", "NA", "PENDING", "ERROR", "REVIEW"} else "REVIEW"


# Inherited hooks retain their legacy callable metadata and descriptor objects.
for _method_name in (
    "_append_pending_rows",
    "_group_value",
    "_pending_row_sort_key",
    "_zone_name",
    "_submission_sort_key",
    "_submission_values",
    "_ecr_value",
):
    _method_function = PassportExcelRows.__dict__[_method_name].__func__
    _method_function.__module__ = "app.infrastructure.export.passport_excel_exporter"
    _method_function.__qualname__ = f"PassportExcelExporter.{_method_name}"
del _method_name, _method_function
