from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook

from app.infrastructure.imports.passport_excel_importer import PassportExcelImporter


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    asm = workbook.active
    asm.title = "ASM"
    asm.append(
        [
            "Zone Name",
            "Staffname",
            "StaffCode",
            "Designation",
            "PASSPORT_NO",
            "DOB",
            "DOI",
            "Passport Expiry Date",
        ]
    )
    asm.append(
        [
            "ASSAM",
            "BIPLAB DAS",
            25523,
            "ACE",
            "Z4160891",
            datetime(1979, 9, 5),
            date(2021, 6, 14),
            datetime(2031, 6, 13),
        ]
    )

    delhi = workbook.create_sheet("DE1")
    delhi.append(["Zone Name", "Staff Name", "Staff Code", "Designation", "Gender"])
    delhi.append(["DELHI", "MADHVI KASHYAP", 25293, "ACE", "F"])

    ignored = workbook.create_sheet("Notes")
    ignored.append(["This sheet has no import headers"])
    content = BytesIO()
    workbook.save(content)
    return content.getvalue()


def test_imports_every_worksheet_and_retains_staff_metadata() -> None:
    rows = PassportExcelImporter().import_rows(_workbook_bytes())

    assert len(rows) == 2
    assert rows[0].worksheet_name == "ASM"
    assert rows[0].confirmed_fields == {
        "staff_code": "25523",
        "passport_number": "Z4160891",
        "date_of_birth": "1979-09-05",
        "date_of_issue": "2021-06-14",
        "date_of_expiry": "2031-06-13",
    }
    assert rows[0].staff_metadata["zone_name"] == "ASSAM"
    assert rows[0].staff_metadata["designation"] == "ACE"
    assert rows[0].staff_metadata["source_sheet"] == "ASM"
    assert rows[1].client_name == "MADHVI KASHYAP"
    assert rows[1].staff_metadata["staff_code"] == "25293"


def test_null_markers_are_not_imported_as_passport_values() -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Staffname", "StaffCode", "PASSPORT_NO", "SURNAME"])
    worksheet.append(["A PERSON", 101, "NULL", "N/A"])
    content = BytesIO()
    workbook.save(content)

    row = PassportExcelImporter().import_rows(content.getvalue())[0]

    assert row.confirmed_fields == {"staff_code": "101"}
    assert "passport_no" not in row.staff_metadata


def test_place_of_issue_and_legacy_issuing_country_keep_distinct_meanings() -> None:
    for header, expected_field in (
        ("Place of Issue", "place_of_issue"),
        ("Issuing Country", "issuing_country"),
    ):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["Staffname", header])
        worksheet.append(["A PERSON", "Chennai"])
        content = BytesIO()
        workbook.save(content)

        row = PassportExcelImporter().import_rows(content.getvalue())[0]

        assert row.confirmed_fields[expected_field] == "Chennai"
        unexpected_field = (
            "issuing_country" if expected_field == "place_of_issue" else "place_of_issue"
        )
        assert unexpected_field not in row.confirmed_fields
