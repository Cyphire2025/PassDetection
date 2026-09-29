"""Optional fail-closed workbook budgets; canonical website defaults stay intact."""

from __future__ import annotations

import io
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook
from openpyxl.drawing.spreadsheet_drawing import SpreadsheetDrawing
from openpyxl.worksheet._writer import ALL_TEMP_FILES, WorksheetWriter
from openpyxl.writer.excel import ExcelWriter


class WorkbookCapacityError(ValueError):
    pass


def require_workbook_capacity(
    *, rows: int, columns: int, maximum_cells: int | None, maximum_columns: int | None
) -> None:
    if maximum_columns is not None and columns > maximum_columns:
        raise WorkbookCapacityError("Workbook exceeds its column limit")
    if maximum_cells is not None and rows * columns > maximum_cells:
        raise WorkbookCapacityError("Workbook exceeds its cell limit")


class BoundedWorkbookBuffer(io.BytesIO):
    def __init__(self, maximum: int):
        super().__init__()
        self.maximum = maximum

    def write(self, data: bytes) -> int:  # type: ignore[override]
        if self.tell() + len(data) > self.maximum:
            raise WorkbookCapacityError("Workbook exceeds its output limit")
        return super().write(data)


class _ClosingExcelWriter(ExcelWriter):  # type: ignore[misc]  # openpyxl has no bundled stubs.
    def write_worksheet(self, sheet: Any) -> None:
        # Canonical openpyxl normal-mode writer with cleanup in finally: its
        # original method loses the local XML writer if archive.write raises.
        sheet._drawing = SpreadsheetDrawing()
        sheet._drawing.charts, sheet._drawing.images = sheet._charts, sheet._images
        writer = WorksheetWriter(sheet)
        try:
            writer.write()
            sheet._rels = writer._rels
            self._archive.write(writer.out, sheet.path[1:])
            self.manifest.append(sheet)
        finally:
            writer.close()
            if writer.out in ALL_TEMP_FILES:
                writer.cleanup()


def bounded_workbook_bytes(workbook: Workbook, maximum: int) -> bytes:
    """Close the ZIP writer on a bounded-write error instead of finalizer cleanup."""
    if workbook.write_only:
        raise ValueError("Bounded workbook adapter requires normal worksheet mode")
    with BoundedWorkbookBuffer(maximum) as buffer:
        with ZipFile(buffer, "w", ZIP_DEFLATED, allowZip64=True) as archive:
            _ClosingExcelWriter(workbook, archive).save()
        return buffer.getvalue()
