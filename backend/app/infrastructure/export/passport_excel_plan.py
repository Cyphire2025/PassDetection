"""Build the typed column plan through the exporter's existing policy hooks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.export.passport_excel_columns import _PREFIX_COLUMNS, _ExportColumn
from app.infrastructure.export.passport_excel_phone_columns import is_phone_export_field


class PassportColumnPolicy(Protocol):
    def _enabled_traveller_columns(
        self,
        group_details: dict[uuid.UUID, dict[str, Any]] | None,
        *,
        include_name_history: bool = False,
    ) -> list[_ExportColumn]: ...

    def _custom_fields(
        self,
        submissions: list[PassportSubmission],
        group_details: dict[uuid.UUID, dict[str, Any]] | None,
        *,
        reserved_labels: set[str],
    ) -> list[dict[str, str]]: ...


@dataclass(frozen=True)
class PassportColumnPlan:
    # Preserve the original collection objects passed to row/pending hooks.
    columns: list[_ExportColumn]
    dynamic_fields: list[dict[str, str]]
    headers: list[str]
    group_by_header: str | None


def build_passport_column_plan(
    policy: PassportColumnPolicy,
    submissions: list[PassportSubmission],
    *,
    group_details: dict[uuid.UUID, dict[str, Any]] | None,
    additional_fields: list[dict[str, str]] | None,
    previous_names: dict[uuid.UUID, dict[str, str | None]] | None,
    group_by_field: str | None,
) -> PassportColumnPlan:
    imported_fields = [
        field
        for field in (additional_fields or [])
        if (field.get("key") == "zone_name" or str(field.get("key", "")).startswith("whatsapp:"))
        and field.get("label")
        and not is_phone_export_field(str(field.get("key", "")), str(field["label"]))
    ]
    traveller_columns = policy._enabled_traveller_columns(
        group_details,
        include_name_history=previous_names is not None,
    )
    custom_fields = policy._custom_fields(
        submissions,
        group_details,
        reserved_labels={
            *(column.header.casefold() for column in _PREFIX_COLUMNS),
            *(column.header.casefold() for column in traveller_columns),
            *(str(field["label"]).casefold() for field in imported_fields),
        },
    )
    custom_question_fields = [
        field for field in custom_fields if str(field["key"]).startswith("custom:")
    ]
    custom_detail_fields = [
        field for field in custom_fields if str(field["key"]).startswith("custom_detail:")
    ]
    columns = [
        *_PREFIX_COLUMNS,
        *(_ExportColumn(str(field["label"]), 22) for field in imported_fields),
        *traveller_columns,
        *(_ExportColumn(str(field["label"]), 22) for field in custom_question_fields),
        *(_ExportColumn(str(field["label"]), 22) for field in custom_detail_fields),
    ]
    dynamic_fields = [
        *imported_fields,
        *custom_question_fields,
        *custom_detail_fields,
    ]
    headers = [column.header for column in columns]
    # Name mismatch highlighting is intentionally paused. These columns
    # keep the workbook's normal uploaded-row styling.
    label_by_key = {
        str(field["key"]): str(field["label"])
        for field in imported_fields
        if field.get("key") and field.get("label")
    }
    group_by_header = (
        "International Airport"
        if group_by_field == "international_airport"
        else label_by_key.get(group_by_field or "")
    )
    return PassportColumnPlan(columns, dynamic_fields, headers, group_by_header)
