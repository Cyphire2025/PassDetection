"""Collect one worksheet while retaining the importer's dynamic parser hooks."""

from __future__ import annotations

from itertools import chain, islice
from typing import Any

from . import passport_excel_catalog as catalog
from .passport_excel_limits import _PassportExcelLimits
from .passport_excel_records import (
    ImportedPassportRow,
    PassportExcelImportError,
    _PassportExcelImportState,
    _PassportExcelWorksheetRows,
)


class _PassportExcelWorksheets(_PassportExcelLimits):
    def _collect_worksheet(
        self, worksheet: Any, formula_worksheet: Any, state: _PassportExcelImportState,
    ) -> None:
        if (worksheet.max_column or 0) > catalog.MAX_PASSPORT_EXCEL_COLUMNS:
            raise PassportExcelImportError(
                f"Worksheet {worksheet.title!r} contains too many columns; "
                f"use at most {catalog.MAX_PASSPORT_EXCEL_COLUMNS}."
            )
        row_iterator = worksheet.iter_rows(values_only=True)
        scanned_rows = list(islice(row_iterator, catalog.PASSPORT_EXCEL_HEADER_SCAN_ROWS))
        formula_row_iterator = (
            formula_worksheet.iter_rows(values_only=False)
            if formula_worksheet is not None
            else None
        )
        scanned_formula_rows = (
            list(islice(formula_row_iterator, catalog.PASSPORT_EXCEL_HEADER_SCAN_ROWS))
            if formula_row_iterator is not None
            else []
        )
        if formula_row_iterator is not None and len(scanned_formula_rows) != len(
            scanned_rows
        ):
            raise PassportExcelImportError(
                "The Excel formula and value views are inconsistent."
            )
        state.total_rows += len(scanned_rows)
        self._validate_row_count(state.total_rows)
        if any(
            len(scanned_row) > catalog.MAX_PASSPORT_EXCEL_COLUMNS
            for scanned_row in scanned_rows
        ):
            raise PassportExcelImportError(
                f"Worksheet {worksheet.title!r} contains too many columns; "
                f"use at most {catalog.MAX_PASSPORT_EXCEL_COLUMNS}."
            )
        if not scanned_rows:
            return
        scanned_text_rows = [
            tuple(self._stringify(value) for value in scanned_row)
            for scanned_row in scanned_rows
        ]
        scanned_formula_usage = [
            self._formula_row_usage(formula_row)
            for formula_row in scanned_formula_rows
        ]
        header_index = self._find_header_row(scanned_rows)
        if header_index is None:
            # Do not heuristically interpret note/lookup sheets as
            # passenger data when no exact identity header is present.
            # Still drain and budget every row so an auxiliary sheet
            # cannot bypass workbook-wide resource limits by omitting
            # its optional OpenXML dimension metadata.
            for scanned_index, text_values in enumerate(scanned_text_rows):
                formula_columns, formula_source_characters = (
                    scanned_formula_usage[scanned_index]
                    if scanned_formula_usage
                    else (frozenset(), 0)
                )
                self._charge_unmapped_row(
                    state, text_values,
                    formula_columns=formula_columns,
                    formula_source_characters=formula_source_characters,
                )
            for values in row_iterator:
                state.total_rows += 1
                self._validate_row_count(state.total_rows)
                if len(values) > catalog.MAX_PASSPORT_EXCEL_COLUMNS:
                    raise PassportExcelImportError(
                        f"Worksheet {worksheet.title!r} contains too many columns; "
                        f"use at most {catalog.MAX_PASSPORT_EXCEL_COLUMNS}."
                    )
                formula_columns, formula_source_characters = (
                    self._next_formula_row_usage(formula_row_iterator)
                )
                text_values = tuple(self._stringify(value) for value in values)
                self._charge_unmapped_row(
                    state, text_values,
                    formula_columns=formula_columns,
                    formula_source_characters=formula_source_characters,
                )
            return

        state.readable_sheet_count += 1
        for scanned_index, text_values in enumerate(
            scanned_text_rows[: header_index + 1]
        ):
            formula_columns, formula_source_characters = (
                scanned_formula_usage[scanned_index]
                if scanned_formula_usage
                else (frozenset(), 0)
            )
            self._charge_unmapped_row(
                state, text_values,
                formula_columns=formula_columns,
                formula_source_characters=formula_source_characters,
            )
        header_row = scanned_rows[header_index]
        if scanned_formula_rows and any(
            cell.data_type == "f" for cell in scanned_formula_rows[header_index]
        ):
            raise PassportExcelImportError(
                f"Worksheet {worksheet.title!r} uses a formula in its header row; "
                "replace formula headers with plain text."
            )
        headers = self._map_headers(
            header_row,
            worksheet_name=worksheet.title,
        )
        metadata_headers = self._metadata_headers(header_row)
        data_rows = chain(scanned_rows[header_index + 1 :], row_iterator)
        formula_rows = (
            chain(
                scanned_formula_rows[header_index + 1 :],
                formula_row_iterator,
            )
            if formula_row_iterator is not None
            else None
        )
        first_row_number = header_index + 2

        self._collect_passenger_rows(
            _PassportExcelWorksheetRows(
                worksheet=worksheet,
                scanned_rows=scanned_rows,
                headers=headers,
                metadata_headers=metadata_headers,
                data_rows=data_rows,
                formula_rows=formula_rows,
                first_row_number=first_row_number,
            ),
            state,
        )

    def _collect_passenger_rows(
        self, rows: _PassportExcelWorksheetRows, state: _PassportExcelImportState,
    ) -> None:
        for row_number, values in enumerate(
            rows.data_rows,
            start=rows.first_row_number,
        ):
            if row_number > len(rows.scanned_rows):
                state.total_rows += 1
                self._validate_row_count(state.total_rows)
            if len(values) > catalog.MAX_PASSPORT_EXCEL_COLUMNS:
                raise PassportExcelImportError(
                    f"Worksheet {rows.worksheet.title!r} contains too many columns; "
                    f"use at most {catalog.MAX_PASSPORT_EXCEL_COLUMNS}."
                )
            formula_columns: frozenset[int] = frozenset()
            formula_source_characters = 0
            if rows.formula_rows is not None:
                formula_row = next(rows.formula_rows, None)
                if formula_row is None:
                    raise PassportExcelImportError(
                        "The Excel formula and value views are inconsistent."
                    )
                formula_columns, formula_source_characters = (
                    self._formula_row_usage(formula_row)
                )
            text_values = tuple(self._stringify(value) for value in values)
            populated_cells, materialized_characters = (
                self._row_materialized_usage(
                    text_values,
                    formula_columns=formula_columns,
                    formula_source_characters=formula_source_characters,
                    metadata_headers=rows.metadata_headers,
                )
            )
            state.total_populated_cells += populated_cells
            state.total_metadata_characters += materialized_characters
            self._validate_materialized_budget(
                total_populated_cells=state.total_populated_cells,
                total_metadata_characters=state.total_metadata_characters,
            )
            if not values or self._is_repeated_header_row(values, rows.headers):
                continue
            if not any(text_values) and not formula_columns:
                continue

            mapped = self._map_row(
                rows.headers,
                text_values,
                source_row=values,
                formula_columns=formula_columns,
            )
            # Passport name parts are explicit identity evidence and
            # always outrank a generic Name/Staffname column.
            client_name = self._name_from_parts(mapped) or mapped.get("client_name")
            if not client_name:
                continue

            confirmed_fields = self._confirmed_fields(mapped)
            staff_metadata = self._map_metadata_row(
                rows.metadata_headers,
                text_values,
                formula_columns=formula_columns,
            )
            if mapped.get("staff_code"):
                staff_metadata.setdefault("staff_code", mapped["staff_code"])
            if mapped.get("verified_whatsapp_numbers"):
                staff_metadata["verified_whatsapp_numbers"] = mapped["verified_whatsapp_numbers"]
            staff_metadata["source_sheet"] = rows.worksheet.title
            # A zone heading is not guaranteed in third-party templates;
            # the worksheet name remains a reliable grouping fallback.
            staff_metadata["source_zone"] = (
                staff_metadata.get("zone_name") or rows.worksheet.title
            )
            state.imported.append(
                ImportedPassportRow(
                    row_number=row_number,
                    worksheet_name=rows.worksheet.title,
                    client_name=self._bounded_value(
                        client_name,
                        limit=255,
                        label="Passenger name",
                    )
                    or "",
                    client_email=self._normalize_email(mapped.get("client_email")),
                    client_phone=self._bounded_value(
                        mapped.get("client_phone"),
                        limit=32,
                        label="Phone number",
                    ),
                    departure_city=self._bounded_value(
                        mapped.get("departure_city"),
                        limit=120,
                        label="Departure city",
                    ),
                    nearest_domestic_airport=self._bounded_value(
                        mapped.get("nearest_domestic_airport"),
                        limit=120,
                        label="Nearest domestic airport",
                    ),
                    confirmed_fields=confirmed_fields,
                    staff_metadata=staff_metadata,
                )
            )
