"""Finalize passport tables, change history and bounded XLSX serialization."""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.export.passport_excel_columns import _ExportColumn
from app.infrastructure.export.workbook_capacity import bounded_workbook_bytes
from app.infrastructure.export.workbook_values import safe_xlsx_value as _safe_xlsx_value


def finalize_passport_workbook(
    workbook: Workbook,
    worksheet: Any,
    *,
    columns: list[_ExportColumn],
    headers: list[str],
    header_row: int,
    row_index: int,
    ordered_rows: list[tuple[PassportSubmission, dict[str, Any]]],
    pending_rows: list[dict[str, Any]] | None,
    change_rows: list[dict[str, str]] | None,
    maximum_output_bytes: int | None,
) -> bytes:
    if ordered_rows or pending_rows:
        last_column = worksheet.cell(row=header_row, column=len(headers)).column_letter
        table_ref = f"A{header_row}:{last_column}{row_index}"
        table = Table(displayName="PassportSubmissions", ref=table_ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        worksheet.add_table(table)

    for index, column in enumerate(columns, start=1):
        column_letter = worksheet.cell(row=header_row, column=index).column_letter
        worksheet.column_dimensions[column_letter].width = column.width

    if change_rows is not None:
        changes = workbook.create_sheet("Changes")
        changes.append(["Submission ID", "Change", "Previous revision", "Current revision"])
        for cell in changes[1]:
            cell.font = Font(bold=True)
        for change in change_rows:
            changes.append(
                [
                    _safe_xlsx_value(change[key])
                    for key in (
                        "submission_id",
                        "change",
                        "previous_revision",
                        "revision",
                    )
                ]
            )
        changes.freeze_panes = "A2"
        changes.auto_filter.ref = changes.dimensions
        for column_name, width in (("A", 40), ("B", 16), ("C", 68), ("D", 68)):
            changes.column_dimensions[column_name].width = width

    if maximum_output_bytes is not None:
        return bounded_workbook_bytes(workbook, maximum_output_bytes)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
