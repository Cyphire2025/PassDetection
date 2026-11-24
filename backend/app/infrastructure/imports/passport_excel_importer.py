"""Read bounded canonical passenger rows through stable public import contracts."""

from __future__ import annotations

import io
import re
from typing import Final
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from . import passport_excel_catalog as catalog
from .passport_excel_catalog import _build_header_alias_index as _build_header_alias_index
from .passport_excel_catalog import (
    _canonicalize_numeric_date_separators as _canonicalize_numeric_date_separators,
)
from .passport_excel_catalog import _header_identity as _header_identity
from .passport_excel_catalog import _HeaderAlias as _HeaderAlias
from .passport_excel_catalog import _normalized_header_text as _normalized_header_text
from .passport_excel_records import ImportedPassportRow as ImportedPassportRow
from .passport_excel_records import PassportExcelImportError as PassportExcelImportError
from .passport_excel_records import _PassportExcelImportState
from .passport_excel_worksheets import _PassportExcelWorksheets

MAX_PASSPORT_EXCEL_WORKSHEETS: Final[int] = catalog.MAX_PASSPORT_EXCEL_WORKSHEETS
MAX_PASSPORT_EXCEL_ROWS: Final[int] = catalog.MAX_PASSPORT_EXCEL_ROWS
MAX_PASSPORT_EXCEL_COLUMNS: Final[int] = catalog.MAX_PASSPORT_EXCEL_COLUMNS
MAX_PASSPORT_EXCEL_ARCHIVE_MEMBERS: Final[int] = catalog.MAX_PASSPORT_EXCEL_ARCHIVE_MEMBERS
MAX_PASSPORT_EXCEL_UNCOMPRESSED_BYTES: Final[int] = catalog.MAX_PASSPORT_EXCEL_UNCOMPRESSED_BYTES
MAX_PASSPORT_EXCEL_COMPRESSION_RATIO: Final[int] = catalog.MAX_PASSPORT_EXCEL_COMPRESSION_RATIO
PASSPORT_EXCEL_COMPRESSION_RATIO_MIN_BYTES: Final[int] = catalog.PASSPORT_EXCEL_COMPRESSION_RATIO_MIN_BYTES
PASSPORT_EXCEL_HEADER_SCAN_ROWS: Final[int] = catalog.PASSPORT_EXCEL_HEADER_SCAN_ROWS
MAX_PASSPORT_NUMBER_LENGTH: Final[int] = catalog.MAX_PASSPORT_NUMBER_LENGTH
MAX_PASSPORT_EXCEL_CELL_CHARACTERS: Final[int] = catalog.MAX_PASSPORT_EXCEL_CELL_CHARACTERS
MAX_PASSPORT_EXCEL_POPULATED_CELLS: Final[int] = catalog.MAX_PASSPORT_EXCEL_POPULATED_CELLS
MAX_PASSPORT_EXCEL_METADATA_CHARACTERS: Final[int] = catalog.MAX_PASSPORT_EXCEL_METADATA_CHARACTERS
_NAME_FIELDS: Final[frozenset[str]] = catalog._NAME_FIELDS
_DATE_FIELDS: Final[frozenset[str]] = catalog._DATE_FIELDS
_RESERVED_METADATA_KEYS: Final[frozenset[str]] = catalog._RESERVED_METADATA_KEYS
_EMPTY_CELL_VALUES: Final[frozenset[str]] = catalog._EMPTY_CELL_VALUES
_EXCEL_ERROR_CELL_VALUES: Final[frozenset[str]] = catalog._EXCEL_ERROR_CELL_VALUES
_MIXED_NUMERIC_DATE_PATTERN: Final[re.Pattern[str]] = catalog._MIXED_NUMERIC_DATE_PATTERN
_HEADER_ALIASES: Final[dict[str, tuple[str, ...]]] = catalog._HEADER_ALIASES
_HEADER_ALIAS_INDEX: Final[dict[str, _HeaderAlias]] = catalog._HEADER_ALIAS_INDEX


class PassportExcelImporter(_PassportExcelWorksheets):
    """Convert an untrusted XLSX workbook into bounded canonical row data."""

    HEADER_ALIASES = catalog._HEADER_ALIASES
    FIELD_KEYS = _PassportExcelWorksheets.FIELD_KEYS

    def import_rows(self, content: bytes) -> list[ImportedPassportRow]:
        contains_formulas = self._validate_archive(content)
        workbook = None
        formula_workbook = None
        try:
            workbook = load_workbook(
                io.BytesIO(content),
                data_only=True,
                read_only=True,
                keep_links=False,
            )
            if contains_formulas:
                # The data-only view intentionally never executes formulas, but
                # it cannot distinguish a blank cell from a formula with no
                # cached result. A second read-only view is opened only for
                # formula-bearing workbooks so canonical identity fields can
                # fail closed without doubling the normal import hot path.
                formula_workbook = load_workbook(
                    io.BytesIO(content),
                    data_only=False,
                    read_only=True,
                    keep_links=False,
                )
            if len(workbook.worksheets) > catalog.MAX_PASSPORT_EXCEL_WORKSHEETS:
                raise PassportExcelImportError(
                    "The Excel file contains too many worksheets; "
                    f"use at most {catalog.MAX_PASSPORT_EXCEL_WORKSHEETS}."
                )
            # OpenXML dimension metadata is optional. Workbooks created by
            # streaming writers can legitimately report ``None`` here; the
            # row iterator below remains the authoritative bounded check.
            if sum((worksheet.max_row or 0) for worksheet in workbook.worksheets) > (
                catalog.MAX_PASSPORT_EXCEL_ROWS
            ):
                raise PassportExcelImportError(
                    "The Excel file contains too many rows; "
                    f"use at most {catalog.MAX_PASSPORT_EXCEL_ROWS} across all worksheets."
                )

            state = _PassportExcelImportState()
            for worksheet in workbook.worksheets:
                formula_worksheet = (
                    formula_workbook[worksheet.title]
                    if formula_workbook is not None
                    else None
                )
                self._collect_worksheet(worksheet, formula_worksheet, state)
        except PassportExcelImportError:
            raise
        except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
            raise PassportExcelImportError("The uploaded Excel file could not be read.") from exc
        finally:
            if workbook is not None:
                workbook.close()
            if formula_workbook is not None:
                formula_workbook.close()

        if not state.readable_sheet_count:
            raise PassportExcelImportError(
                "Could not find a header row in any worksheet of the Excel file"
            )
        return state.imported
