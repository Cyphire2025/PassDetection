"""Agency-ready passport workbook orchestration with stable public export hooks."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.export import workbook_values as _workbook_values
from app.infrastructure.export.ecr_excel_exporter import ecr_result_font
from app.infrastructure.export.passport_excel_columns import (
    _COLUMNS,
    _ECR_COLUMN,
    _NAME_HISTORY_COLUMNS,
    _ZONE_SEPARATOR_BLANK_ROWS,
    _custom_fields,
    _enabled_traveller_columns,
)
from app.infrastructure.export.passport_excel_columns import (
    _EXCEL_DATE_NUMBER_FORMAT as _EXCEL_DATE_NUMBER_FORMAT,
)
from app.infrastructure.export.passport_excel_columns import (
    _PENDING_ROW_FILL as _PENDING_ROW_FILL,
)
from app.infrastructure.export.passport_excel_columns import (
    _PREFIX_COLUMNS as _PREFIX_COLUMNS,
)
from app.infrastructure.export.passport_excel_columns import (
    _TRAVELLER_COLUMNS as _TRAVELLER_COLUMNS,
)
from app.infrastructure.export.passport_excel_columns import (
    _ExportColumn as _ExportColumn,
)
from app.infrastructure.export.passport_excel_phone_columns import (
    is_phone_export_field as is_phone_export_field,
)
from app.infrastructure.export.passport_excel_plan import build_passport_column_plan
from app.infrastructure.export.passport_excel_rows import PassportExcelRows as _PassportExcelRows
from app.infrastructure.export.passport_excel_values import (
    _country_display_name as _country_display_name,
)
from app.infrastructure.export.passport_excel_values import (
    _date_value as _date_value,
)
from app.infrastructure.export.passport_excel_values import (
    _export_cell_value,
)
from app.infrastructure.export.passport_excel_values import (
    _gender_display_value as _gender_display_value,
)
from app.infrastructure.export.passport_excel_values import (
    _nationality_display_value as _nationality_display_value,
)
from app.infrastructure.export.passport_excel_values import (
    _uppercase as _uppercase,
)
from app.infrastructure.export.passport_excel_values import (
    _whatsapp_phone_value as _whatsapp_phone_value,
)
from app.infrastructure.export.passport_excel_values import (
    passport_age_group as passport_age_group,
)
from app.infrastructure.export.passport_excel_workbook import finalize_passport_workbook
from app.infrastructure.export.workbook_capacity import require_workbook_capacity

# Existing callers import these conversion aliases from the public exporter.
_excel_date_value = _workbook_values.excel_date_value
_safe_xlsx_value = _workbook_values.safe_xlsx_value


class PassportExcelExporter(_PassportExcelRows):
    HEADERS = list(
        dict.fromkeys(
            [
                *(column.header for column in _COLUMNS),
                *(column.header for column in _NAME_HISTORY_COLUMNS),
                _ECR_COLUMN.header,
            ]
        )
    )

    _enabled_traveller_columns = staticmethod(_enabled_traveller_columns)
    _custom_fields = staticmethod(_custom_fields)

    def export_group(
        self,
        submissions: list[PassportSubmission],
        *,
        group_name: str,
        group_details: dict[uuid.UUID, dict[str, Any]] | None = None,
        zone_names: dict[uuid.UUID, str] | None = None,
        additional_fields: list[dict[str, str]] | None = None,
        additional_values: dict[uuid.UUID, dict[str, str | None]] | None = None,
        whatsapp_contacts: dict[
            uuid.UUID,
            dict[str, str | None],
        ]
        | None = None,
        previous_names: dict[
            uuid.UUID,
            dict[str, str | None],
        ]
        | None = None,
        group_by_field: str | None = None,
        pending_rows: list[dict[str, Any]] | None = None,
        change_rows: list[dict[str, str]] | None = None,
        ecr_results: dict[uuid.UUID, str] | None = None,
        maximum_cells: int | None = None,
        maximum_columns: int | None = None,
        maximum_output_bytes: int | None = None,
    ) -> bytes:
        plan = build_passport_column_plan(
            self,
            submissions,
            group_details=group_details,
            additional_fields=additional_fields,
            previous_names=previous_names,
            group_by_field=group_by_field,
        )
        columns = plan.columns
        dynamic_fields = plan.dynamic_fields
        headers = plan.headers
        group_by_header = plan.group_by_header
        # Up to two separator rows per source row, plus the four-row header.
        # Check before openpyxl allocates cells or styles; never truncate output.
        require_workbook_capacity(
            rows=5 + 3 * (len(submissions) + len(pending_rows or [])) + len(change_rows or []),
            columns=len(headers),
            maximum_cells=maximum_cells,
            maximum_columns=maximum_columns,
        )
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Passport Submissions"

        worksheet["A1"] = f"Passport Export - {group_name}"
        worksheet["A1"].font = Font(bold=True, size=14)
        worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        generated_at = datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        worksheet["A2"] = f"Generated at {generated_at}"
        worksheet["A2"].font = Font(color="64748B")
        worksheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))

        worksheet.append([])
        worksheet.append(headers)
        header_row = 4
        for cell in worksheet[header_row]:
            # Dynamic labels are intentionally preserved verbatim, but must be
            # stored as text so formula-leading values cannot execute on open.
            cell.data_type = "s"
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1D4ED8")
            cell.alignment = Alignment(horizontal="center")

        prepared_rows: list[tuple[PassportSubmission, dict[str, Any]]] = []
        for submission in submissions:
            prepared_rows.append(
                (
                    submission,
                    self._submission_values(
                        submission,
                        group_name=group_name,
                        details=(group_details or {}).get(submission.group_id, {}),
                        zone_names=zone_names,
                        dynamic_fields=dynamic_fields,
                        additional_values=additional_values,
                        whatsapp_contacts=whatsapp_contacts,
                        previous_names=previous_names,
                        ecr_results=ecr_results,
                    ),
                )
            )
        ordered_rows = sorted(
            prepared_rows,
            key=lambda item: self._submission_sort_key(
                item[0],
                item[1],
                group_by_header=group_by_header,
            ),
        )
        previous_group_key: str | None = None
        has_written_submission = False
        row_index = header_row
        for submission, values in ordered_rows:
            group_key = self._group_value(values, group_by_header).casefold()
            if group_by_header and has_written_submission and group_key != previous_group_key:
                # Keep operational batches visually separate without mutating
                # the underlying submission or WhatsApp data.
                for _ in range(_ZONE_SEPARATOR_BLANK_ROWS):
                    worksheet.append([])
                    row_index += 1
            row_values = []
            for column in columns:
                value = values[column.header]
                row_values.append(_export_cell_value(column, value))
            worksheet.append(row_values)
            row_index += 1
            for column_index, column in enumerate(columns, start=1):
                cell = worksheet.cell(row=row_index, column=column_index)
                if column.number_format and isinstance(cell.value, (date, datetime)):
                    cell.number_format = column.number_format
                if column.header == "ECR" and cell.value:
                    cell.font = ecr_result_font(str(cell.value))
            previous_group_key = group_key
            has_written_submission = True

        if pending_rows:
            row_index = self._append_pending_rows(
                worksheet,
                after_row=row_index,
                columns=columns,
                pending_rows=pending_rows,
                group_by_header=group_by_header,
            )

        return finalize_passport_workbook(
            workbook,
            worksheet,
            columns=columns,
            headers=headers,
            header_row=header_row,
            row_index=row_index,
            ordered_rows=ordered_rows,
            pending_rows=pending_rows,
            change_rows=change_rows,
            maximum_output_bytes=maximum_output_bytes,
        )
