"""Stable public row and error contracts for canonical workbook imports."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


class PassportExcelImportError(ValueError):
    """A safe, user-actionable workbook import failure."""


@dataclass(frozen=True)
class ImportedPassportRow:
    row_number: int
    worksheet_name: str
    client_name: str
    client_email: str | None
    client_phone: str | None
    departure_city: str | None
    nearest_domestic_airport: str | None
    confirmed_fields: dict[str, str]
    staff_metadata: dict[str, str]

# Keep existing public class paths while their definitions have a focused owner.
ImportedPassportRow.__module__ = "app.infrastructure.imports.passport_excel_importer"
PassportExcelImportError.__module__ = "app.infrastructure.imports.passport_excel_importer"


@dataclass
class _PassportExcelImportState:
    """Per-call row results and workbook-wide counters, without callable hooks."""

    imported: list[ImportedPassportRow] = field(default_factory=list)
    readable_sheet_count: int = 0
    total_rows: int = 0
    total_populated_cells: int = 0
    total_metadata_characters: int = 0


@dataclass(frozen=True)
class _PassportExcelWorksheetRows:
    """One sheet's existing row iterators and header data, without callbacks."""

    worksheet: Any
    scanned_rows: list[tuple[Any, ...]]
    headers: dict[int, str]
    metadata_headers: dict[int, str]
    data_rows: Iterator[tuple[Any, ...]]
    formula_rows: Iterator[tuple[Any, ...]] | None
    first_row_number: int
