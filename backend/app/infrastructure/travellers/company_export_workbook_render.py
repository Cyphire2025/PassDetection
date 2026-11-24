"""Streaming private workbook rendering and explicit temporary-resource ownership."""

import tempfile
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell

from app.application.companies.export_source import EXCEL_HEADERS
from app.infrastructure.travellers.company_export_limits import MAX_EXCEL_PEOPLE, MAX_PART_BYTES


class WorkbookAssembly:
    """O(one page) RAM and <=256 MiB temporary XML/output; no dataset list."""

    def __init__(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="company-export-")
        self.path = Path(self.directory.name) / "people.xlsx"
        self.workbook = Workbook(write_only=True)
        self.sheet = self.workbook.create_sheet("Current people")
        self.count = 0
        self.append([list(EXCEL_HEADERS)])
        self.count = 0

    def append(self, rows: list[list[str | int]]) -> None:
        self.count += len(rows)
        if self.count > MAX_EXCEL_PEOPLE:
            raise ValueError("export_people_limit")
        for row in rows:
            cells = []
            for value in row:
                cell = WriteOnlyCell(self.sheet, value=value)
                if isinstance(value, str):
                    cell.data_type = "s"  # Untrusted '=...' remains text.
                cells.append(cell)
            self.sheet.append(cells)
        writer: Any = self.sheet._writer
        if writer is not None and Path(writer.out).stat().st_size > 256 * 1024 * 1024:
            raise ValueError("export_temporary_disk_limit")

    def finish(self) -> bytes:
        self.workbook.save(self.path)
        if self.path.stat().st_size > MAX_PART_BYTES:
            raise ValueError("export_workbook_byte_limit")
        return self.path.read_bytes()

    def close(self) -> None:
        writer: Any = self.sheet._writer
        try:
            if not self.sheet.closed:
                self.sheet.close()
            self.workbook.close()
            if writer is not None:
                writer.cleanup()
        except (FileNotFoundError, OSError):
            pass
        finally:
            self.directory.cleanup()
