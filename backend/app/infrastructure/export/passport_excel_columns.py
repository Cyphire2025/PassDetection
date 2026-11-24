"""Stable passport workbook columns and configured supplemental field policy."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from openpyxl.styles import PatternFill

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.export.passport_excel_phone_columns import (
    VERIFIED_WHATSAPP_HEADER,
    is_phone_export_field,
)


@dataclass(frozen=True)
class _ExportColumn:
    header: str
    width: int
    enabled_flag: str | None = None
    number_format: str | None = None


# Keep the existing public dataclass and pickle import identity.
_ExportColumn.__module__ = "app.infrastructure.export.passport_excel_exporter"


_EXCEL_DATE_NUMBER_FORMAT = "DD.MM.YYYY"

_PREFIX_COLUMNS = (
    _ExportColumn("Group", 24),
    _ExportColumn("Destination", 22),
    _ExportColumn("Travel/Departure Date", 22, number_format=_EXCEL_DATE_NUMBER_FORMAT),
    _ExportColumn("Return Date", 16, number_format=_EXCEL_DATE_NUMBER_FORMAT),
)

_TRAVELLER_COLUMNS = (
    _ExportColumn(
        "Agency/Dealership Name",
        28,
        "agency_dealership_name_enabled",
    ),
    _ExportColumn("Staff Code", 18, "staff_code_enabled"),
    _ExportColumn(
        "Agent/Employee Code",
        24,
        "agent_employee_code_enabled",
    ),
    _ExportColumn("Designation", 22, "designation_enabled"),
    _ExportColumn(
        "Relation with Qualifier",
        24,
        "relation_with_qualifier_enabled",
    ),
    _ExportColumn("Age Group", 14),
    _ExportColumn("Base City", 20, "base_city_enabled"),
    _ExportColumn(
        "Domestic Airport",
        26,
        "ask_nearest_domestic_airport",
    ),
    _ExportColumn("WhatsApp Email", 28),
    _ExportColumn("Meal Preference", 18, "meal_preference_enabled"),
    _ExportColumn(
        "International Airport",
        28,
        "nearest_international_airport_enabled",
    ),
    _ExportColumn("SURNAME", 20),
    _ExportColumn("GIVEN NAME", 24),
    _ExportColumn("GENDER", 12),
    _ExportColumn("Passport Number", 20),
    _ExportColumn("DOB", 16, number_format=_EXCEL_DATE_NUMBER_FORMAT),
    _ExportColumn("DOI", 16, number_format=_EXCEL_DATE_NUMBER_FORMAT),
    _ExportColumn("DOE", 16, number_format=_EXCEL_DATE_NUMBER_FORMAT),
    _ExportColumn("Place of Issue", 22),
    _ExportColumn("Nationality", 22),
    _ExportColumn("Upload Email", 28),
    _ExportColumn(VERIFIED_WHATSAPP_HEADER, 28),
)

_COLUMNS = _PREFIX_COLUMNS + _TRAVELLER_COLUMNS

_ECR_COLUMN = _ExportColumn("ECR", 16)

_NAME_HISTORY_COLUMNS = (
    _ExportColumn("Old Given Name", 24),
    _ExportColumn("New Surname", 20),
    _ExportColumn("New Given Name", 24),
)

_PENDING_ROW_FILL = PatternFill("solid", fgColor="FFF2CC")

_ZONE_SEPARATOR_BLANK_ROWS = 2


def _enabled_traveller_columns(
    group_details: dict[uuid.UUID, dict[str, Any]] | None,
    *,
    include_name_history: bool = False,
) -> list[_ExportColumn]:
    if group_details is None:
        enabled_columns = list(_TRAVELLER_COLUMNS)
    else:
        # Callers provide details only for groups included in the workbook.
        # Consider every included group so a pending-only group can still
        # enable and export its configured optional fields.
        relevant_details = list(group_details.values())
        if not relevant_details:
            enabled_columns = list(_TRAVELLER_COLUMNS)
        else:
            enabled_columns = [
                column
                for column in _TRAVELLER_COLUMNS
                if (
                    column.enabled_flag is None
                    or any(
                        bool(details.get(column.enabled_flag, False))
                        for details in relevant_details
                    )
                )
            ]

    if group_details and any(
        details.get("passport_ecr_enabled") for details in group_details.values()
    ):
        enabled_columns.append(_ECR_COLUMN)

    if not include_name_history:
        return enabled_columns

    with_name_history: list[_ExportColumn] = []
    for column in enabled_columns:
        if column.header == "SURNAME":
            with_name_history.extend(_NAME_HISTORY_COLUMNS)
        elif column.header != "GIVEN NAME":
            with_name_history.append(column)
    return with_name_history


def _custom_fields(
    submissions: list[PassportSubmission],
    group_details: dict[uuid.UUID, dict[str, Any]] | None,
    *,
    reserved_labels: set[str],
) -> list[dict[str, str]]:
    """Build stable question/detail columns, preserving configuration order."""

    definitions: list[tuple[str, str, str]] = []
    seen_keys: set[str] = set()

    def add(key: str, label: str, source_label: str) -> None:
        normalized_label = " ".join(str(label).strip().split())
        if (
            not key
            or key in seen_keys
            or not normalized_label
            or is_phone_export_field(key, normalized_label)
        ):
            return
        seen_keys.add(key)
        definitions.append((key, normalized_label[:120], source_label))

    for details in (group_details or {}).values():
        for question in details.get("custom_questions") or []:
            if question.get("enabled"):
                add(
                    f"custom:{question.get('id')}",
                    str(question.get("label") or ""),
                    "Custom Question",
                )
        for detail in details.get("custom_details") or []:
            if detail.get("enabled"):
                add(
                    f"custom_detail:{detail.get('id')}",
                    str(detail.get("label") or ""),
                    "Custom Detail",
                )

    for submission in submissions:
        for answer in getattr(submission, "custom_answers", []) or []:
            add(
                f"custom:{answer.get('question_id')}",
                str(answer.get("label") or ""),
                "Custom Question",
            )
        for answer in getattr(submission, "custom_detail_answers", []) or []:
            add(
                f"custom_detail:{answer.get('detail_id')}",
                str(answer.get("label") or ""),
                "Custom Detail",
            )

    fields: list[dict[str, str]] = []
    used_labels = set(reserved_labels)
    for key, label, source_label in definitions:
        candidate = label
        suffix_index = 1
        while candidate.casefold() in used_labels:
            suffix = (
                f" ({source_label})" if suffix_index == 1 else f" ({source_label} {suffix_index})"
            )
            candidate = f"{label[: max(1, 120 - len(suffix))]}{suffix}"
            suffix_index += 1
        used_labels.add(candidate.casefold())
        fields.append({"key": key, "label": candidate})
    return fields


# Direct staticmethod aliases keep the existing public callable identity.
for _policy in (_enabled_traveller_columns, _custom_fields):
    _policy.__module__ = "app.infrastructure.export.passport_excel_exporter"
    _policy.__qualname__ = f"PassportExcelExporter.{_policy.__name__}"
del _policy
