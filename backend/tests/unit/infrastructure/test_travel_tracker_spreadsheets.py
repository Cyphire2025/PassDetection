from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from app.infrastructure.travel_tracker.spreadsheets import (
    TrackerSpreadsheetError,
    match_rows,
    read_rows,
)


def workbook_bytes(rows):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


@pytest.mark.parametrize(
    "filename,content",
    [
        ("data.xls", b"bad"),
        ("data.xlsx", b"not zip"),
        ("data.csv", b"Name\n\xff"),
        ("data.csv", b"Name\n"),
        ("data.csv", b"Unexpected\nNobody"),
    ],
)
def test_invalid_format_or_empty_sheet_has_useful_input_error(filename, content):
    with pytest.raises(TrackerSpreadsheetError):
        read_rows(content, filename)


def test_traditional_export_title_rows_and_given_surname_headers():
    rows = read_rows(
        workbook_bytes(
            [
                ["Title"],
                ["Generated today"],
                [],
                ["GIVEN NAME", "SURNAME", "Passport Number"],
                ["Asha", "Rao", "P42"],
            ]
        ),
        "names.xlsx",
    )
    assert rows[0]["row_number"] == 5 and rows[0]["name"] == "Asha Rao"


def test_limits_rows_and_columns():
    with pytest.raises(TrackerSpreadsheetError, match="1,000"):
        read_rows(("Name\n" + "Asha\n" * 1001).encode(), "names.csv")
    with pytest.raises(TrackerSpreadsheetError, match="256"):
        read_rows(("Name," + "," * 256).encode(), "names.csv")


def test_malformed_worksheet_xml_is_a_controlled_input_error():
    good = workbook_bytes([["Name"], ["Asha"]])
    buffer = io.BytesIO()
    with ZipFile(io.BytesIO(good)) as source, ZipFile(buffer, "w") as target:
        for entry in source.infolist():
            target.writestr(
                entry.filename,
                b"<invalid"
                if entry.filename == "xl/worksheets/sheet1.xml"
                else source.read(entry.filename),
            )
    with pytest.raises(TrackerSpreadsheetError, match="could not be read"):
        read_rows(buffer.getvalue(), "names.xlsx")


def test_strong_id_never_falls_back_to_name_in_another_group_and_duplicates_are_unique():
    passenger = SimpleNamespace(
        id=uuid.uuid4(),
        client_name="Asha Rao",
        confirmed_fields={"passport_number": "P42"},
        extracted_fields=None,
    )
    records = [
        {"row_number": 2, "id": str(uuid.uuid4()), "name": "Asha Rao"},
        {"row_number": 3, "id": str(passenger.id), "passport": "Wrong", "name": "Asha Rao"},
        {"row_number": 4, "passport": "Wrong", "name": "Asha Rao"},
        {"row_number": 5, "passport": "P 42"},
        {"row_number": 6, "name": "ASHA  RAO"},
        {"row_number": 7, "name": "=1+1"},
    ]
    preview = match_rows(records, [passenger], track="visa", marked=True)
    assert [row.status for row in preview.rows] == [
        "unmatched",
        "unmatched",
        "unmatched",
        "matched",
        "duplicate",
        "unmatched",
    ]
    assert preview.passenger_ids == [passenger.id]
