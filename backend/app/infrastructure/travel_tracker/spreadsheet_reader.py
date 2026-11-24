"""Bounded UTF-8/OOXML import reading; no native identity mutation."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from typing import Any
from zipfile import ZipFile

from openpyxl import load_workbook

from app.infrastructure.travel_tracker.spreadsheet_values import (
    MAX_COLUMNS,
    MAX_IMPORT_ROWS,
    MAX_UPLOAD_BYTES,
    TrackerSpreadsheetError,
    normalized_name,
)


def _header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", normalized_name(value))


_HEADERS = {
    "passengerid": "id",
    "submissionid": "id",
    "id": "id",
    "passportnumber": "passport",
    "passportno": "passport",
    "passport": "passport",
    "name": "name",
    "fullname": "name",
    "passengername": "name",
    "clientname": "name",
    "travellername": "name",
    "travelername": "name",
    "givenname": "given",
    "givennames": "given",
    "firstname": "given",
    "surname": "surname",
    "lastname": "surname",
    "familyname": "surname",
}


def _bounded_rows(rows: Iterable[Iterable[Any]]) -> list[dict[str, Any]]:
    columns: dict[str, int] | None = None
    output: list[dict[str, Any]] = []
    for row_number, raw in enumerate(rows, 1):
        if row_number > MAX_IMPORT_ROWS + 20:
            raise TrackerSpreadsheetError("Import at most 1,000 passengers at a time.")
        values = list(raw)
        if len(values) > MAX_COLUMNS:
            raise TrackerSpreadsheetError("Spreadsheets can contain at most 256 columns.")
        if not any(value not in (None, "") for value in values):
            continue
        if any(len(str(value or "")) > 2048 for value in values):
            raise TrackerSpreadsheetError("Spreadsheet cells can contain at most 2,048 characters.")
        if columns is None:
            candidates = {
                _HEADERS[_header(value)]: index
                for index, value in enumerate(values)
                if _header(value) in _HEADERS
            }
            if (
                "id" in candidates
                or "passport" in candidates
                or "name" in candidates
                or "given" in candidates
            ):
                columns = candidates
                continue
            if row_number >= 20:
                break
            continue
        if len(output) >= MAX_IMPORT_ROWS:
            raise TrackerSpreadsheetError("Import at most 1,000 passengers at a time.")
        record = {
            key: values[index] if index < len(values) else None for key, index in columns.items()
        }
        record["row_number"] = row_number
        if not record.get("name"):
            record["name"] = " ".join(
                str(record.get(key) or "").strip() for key in ("given", "surname")
            ).strip()
        output.append(record)
    if columns is None:
        raise TrackerSpreadsheetError(
            "Add a Name, Passenger ID, or Passport Number column to the file."
        )
    if not output:
        raise TrackerSpreadsheetError("The spreadsheet has no passenger rows.")
    return output


def read_rows(content: bytes, filename: str) -> list[dict[str, Any]]:
    if not content:
        raise TrackerSpreadsheetError("The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise TrackerSpreadsheetError("Upload a file smaller than 8 MB.")
    if filename.lower().endswith(".csv"):
        try:
            source = content.decode("utf-8-sig")
            return _bounded_rows(csv.reader(io.StringIO(source)))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise TrackerSpreadsheetError("Save the CSV using UTF-8 and try again.") from exc
    if not filename.lower().endswith(".xlsx"):
        raise TrackerSpreadsheetError("Upload an .xlsx workbook or a UTF-8 .csv file.")
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(entry.file_size for entry in entries) > 32 * 1024 * 1024:
                raise TrackerSpreadsheetError("The workbook expands beyond the allowed size.")
            for entry in entries:
                path = entry.filename.lower()
                if "vbaproject" in path or "externallinks/" in path or entry.flag_bits & 1:
                    raise TrackerSpreadsheetError(
                        "Remove macros, external workbook links, and encryption before uploading."
                    )
                if (
                    entry.file_size > 1024 * 1024
                    and entry.file_size / max(entry.compress_size, 1) > 250
                ):
                    raise TrackerSpreadsheetError("The workbook has an unsafe compression ratio.")
        workbook = load_workbook(
            io.BytesIO(content), read_only=True, data_only=False, keep_links=False
        )
        try:
            if len(workbook.worksheets) != 1:
                raise TrackerSpreadsheetError(
                    "Use a workbook with one sheet so the update list is unambiguous."
                )
            sheet = workbook.worksheets[0]
            if (sheet.max_column or 0) > MAX_COLUMNS:
                raise TrackerSpreadsheetError("Spreadsheets can contain at most 256 columns.")
            # Ignore declared dimensions and stream actual rows under our limit.
            sheet.reset_dimensions()
            return _bounded_rows(sheet.iter_rows(values_only=True))
        finally:
            workbook.close()
    except TrackerSpreadsheetError:
        raise
    except Exception as exc:
        # Invalid OOXML raises different parser exceptions depending on the
        # optional XML backend. This bounded parser boundary must fail closed.
        raise TrackerSpreadsheetError(
            "The workbook could not be read. Save it as .xlsx and try again."
        ) from exc
