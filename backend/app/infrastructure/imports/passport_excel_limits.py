"""Archive, formula-view and materialized workbook resource checks."""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any
from zipfile import BadZipFile, ZipFile

from . import passport_excel_catalog as catalog
from .passport_excel_formula import WorkbookXMLParseError, worksheet_contains_formula
from .passport_excel_records import PassportExcelImportError, _PassportExcelImportState
from .passport_excel_rows import _PassportExcelRows


class _PassportExcelLimits(_PassportExcelRows):
    """Keep workbook checks on self so existing class/instance overrides apply."""

    def _validate_archive(self, content: bytes) -> bool:
        if not content:
            raise PassportExcelImportError("The uploaded Excel file is empty.")
        try:
            with ZipFile(io.BytesIO(content)) as archive:
                members = archive.infolist()
                if len(members) > catalog.MAX_PASSPORT_EXCEL_ARCHIVE_MEMBERS:
                    raise PassportExcelImportError(
                        "The Excel file contains too many archive entries; "
                        "simplify the workbook and try again."
                    )
                total_uncompressed = sum(member.file_size for member in members)
                if total_uncompressed > catalog.MAX_PASSPORT_EXCEL_UNCOMPRESSED_BYTES:
                    raise PassportExcelImportError(
                        "The Excel file expands beyond the allowed size; "
                        "simplify the workbook and try again."
                    )
                for member in members:
                    if (
                        member.file_size > catalog.PASSPORT_EXCEL_COMPRESSION_RATIO_MIN_BYTES
                        and member.compress_size > 0
                        and member.file_size / member.compress_size
                        > catalog.MAX_PASSPORT_EXCEL_COMPRESSION_RATIO
                    ):
                        raise PassportExcelImportError(
                            "The Excel file has an unsafe compression ratio."
                        )
                return any(
                    self._archive_member_contains_formula(archive, member)
                    for member in members
                    if member.filename.casefold().startswith("xl/worksheets/")
                    and member.filename.casefold().endswith(".xml")
                )
        except (BadZipFile, OSError, RuntimeError, WorkbookXMLParseError) as exc:
            raise PassportExcelImportError("The uploaded Excel file could not be read.") from exc

    def _archive_member_contains_formula(self, archive: ZipFile, member: Any) -> bool:
        with archive.open(member) as source:
            return worksheet_contains_formula(source)

    def _formula_row_usage(
        self,
        row: tuple[Any, ...] | None,
    ) -> tuple[frozenset[int], int]:
        """Return formula columns and bounded source-text size for one row."""

        if row is None:
            return frozenset(), 0
        formula_columns: set[int] = set()
        source_characters = 0
        for index, cell in enumerate(row):
            if getattr(cell, "data_type", None) != "f":
                continue
            formula_columns.add(index)
            source_characters += len(self._stringify(getattr(cell, "value", None)))
        return frozenset(formula_columns), source_characters

    def _next_formula_row_usage(
        self,
        formula_rows: Iterator[tuple[Any, ...]] | None,
    ) -> tuple[frozenset[int], int]:
        if formula_rows is None:
            return frozenset(), 0
        formula_row = next(formula_rows, None)
        if formula_row is None:
            raise PassportExcelImportError(
                "The Excel formula and value views are inconsistent."
            )
        return self._formula_row_usage(formula_row)

    def _row_materialized_usage(
        self,
        text_values: tuple[str, ...],
        *,
        formula_columns: frozenset[int] = frozenset(),
        formula_source_characters: int = 0,
        metadata_headers: dict[int, str] | None = None,
    ) -> tuple[int, int]:
        """Charge formula cells once while bounding both source and cached text."""

        populated_cells = len(formula_columns) + sum(
            bool(value)
            for index, value in enumerate(text_values)
            if index not in formula_columns
        )
        header_names = metadata_headers or {}
        materialized_characters = formula_source_characters + sum(
            len(value) + len(header_names.get(index, ""))
            for index, value in enumerate(text_values)
            if value
        )
        return populated_cells, materialized_characters

    def _validate_row_count(self, total_rows: int) -> None:
        if total_rows > catalog.MAX_PASSPORT_EXCEL_ROWS:
            raise PassportExcelImportError(
                "The Excel file contains too many rows; "
                f"use at most {catalog.MAX_PASSPORT_EXCEL_ROWS} across all worksheets."
            )

    def _validate_materialized_budget(
        self,
        *,
        total_populated_cells: int,
        total_metadata_characters: int,
    ) -> None:
        if total_populated_cells > catalog.MAX_PASSPORT_EXCEL_POPULATED_CELLS:
            raise PassportExcelImportError(
                "The Excel file contains too many populated cells; "
                f"use at most {catalog.MAX_PASSPORT_EXCEL_POPULATED_CELLS}."
            )
        if total_metadata_characters > catalog.MAX_PASSPORT_EXCEL_METADATA_CHARACTERS:
            raise PassportExcelImportError(
                "The Excel file contains too much passenger detail; "
                "remove unnecessary columns or split it into smaller files."
            )


    def _charge_unmapped_row(
        self,
        state: _PassportExcelImportState,
        text_values: tuple[str, ...],
        *,
        formula_columns: frozenset[int],
        formula_source_characters: int,
    ) -> None:
        """Charge header/auxiliary row content before any passenger mapping."""
        populated_cells, materialized_characters = (
            self._row_materialized_usage(
                text_values,
                formula_columns=formula_columns,
                formula_source_characters=formula_source_characters,
            )
        )
        state.total_populated_cells += populated_cells
        state.total_metadata_characters += materialized_characters
        self._validate_materialized_budget(
            total_populated_cells=state.total_populated_cells,
            total_metadata_characters=state.total_metadata_characters,
        )
