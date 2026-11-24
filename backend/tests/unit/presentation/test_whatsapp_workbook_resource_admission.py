"""Real uploaded packages respect limits before avoidable parser allocations."""

from __future__ import annotations

import io
import re
import struct
import zipfile

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from app.application.use_cases.whatsapp.spreadsheet_values import (
    SpreadsheetArchiveCapacityError,
    validate_excel_archive,
)
from app.infrastructure.imports.passport_zip_admission import admit_passport_zip_directory
from app.presentation.api.v1.routes.whatsapp_contact_import import _parse_excel_contact_bytes


def _archive(entries: int) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as package:
        for index in range(entries):
            package.writestr(f"synthetic-{index}.txt", b"")
    return stream.getvalue()


def _count_zipinfo(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    original = zipfile.ZipInfo
    constructions: list[bool] = []

    class CountingZipInfo(original):
        def __init__(self, *args, **kwargs):
            constructions.append(True)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(zipfile, "ZipInfo", CountingZipInfo)
    return constructions


@pytest.mark.parametrize("claimed_entries", [None, 0, 1])
def test_uploaded_excess_directory_rejects_before_any_zipinfo(
    monkeypatch: pytest.MonkeyPatch,
    claimed_entries: int | None,
) -> None:
    payload = bytearray(_archive(10_000))
    assert len(payload) < 5 * 1024 * 1024
    if claimed_entries is not None:
        end = payload.rfind(b"PK\x05\x06")
        struct.pack_into("<HH", payload, end + 8, claimed_entries, claimed_entries)
    constructions = _count_zipinfo(monkeypatch)

    with pytest.raises(HTTPException) as denied:
        _parse_excel_contact_bytes(bytes(payload), filename="synthetic.xlsx")

    assert denied.value.status_code == 400
    assert denied.value.detail == "The Excel contact file contains too many archive entries"
    assert constructions == []


def test_exact_whatsapp_archive_limit_keeps_existing_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _archive(2_000)
    constructions = _count_zipinfo(monkeypatch)

    validate_excel_archive(payload)

    assert len(constructions) == 2_000


def test_passport_and_whatsapp_preserve_independent_member_quotas() -> None:
    payload = _archive(2_500)
    source = io.BytesIO(payload)
    source.seek(7)

    admit_passport_zip_directory(source, max_members=5_000)

    assert source.tell() == 7
    with pytest.raises(SpreadsheetArchiveCapacityError, match="too many archive entries"):
        validate_excel_archive(payload)


def _workbook(*, layout: str = "standard", rows: int = 64) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Contacts"
    if layout == "given_surname":
        sheet.append(["Given Names", "Surname", "Mobile", "Email"])
        sheet.append(["Synthetic", "Traveller", 9876543210, "SYNTHETIC@EXAMPLE.TEST"])
    elif layout == "headerless":
        sheet.append(["Synthetic Traveller", "+91 98765 43210"])
    elif layout == "wide":
        sheet.cell(1, 1, "Name")
        sheet.cell(1, 16_384, "Phone")
        sheet.cell(2, 1, "Synthetic Traveller")
        sheet.cell(2, 16_384, "9876543210")
    else:
        sheet.append(["Name", "Phone"])
        sheet.append(["Synthetic Traveller", "9876543210"])
    for _ in range(rows - sheet.max_row):
        sheet.append([None, None])
    if layout == "multisheet":
        note = book.create_sheet("Unlabelled notes")
        note.append(["Support number 9876543211 is not a contact row"])
        contacts = book.create_sheet("Additional contacts")
        contacts.append(["Name", "Phone"])
        contacts.append(["Second Traveller", "9876543212"])
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def _dimension(payload: bytes, dimension: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as source:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for member in source.infolist():
                content = source.read(member)
                if member.filename == "xl/worksheets/sheet1.xml":
                    content, count = re.subn(
                        rb'<dimension ref="[^"]+"',
                        f'<dimension ref="{dimension}"'.encode(),
                        content,
                    )
                    assert count == 1
                target.writestr(member.filename, content)
    return output.getvalue()


@pytest.mark.parametrize("dimension", [None, "A1:XFD64"])
def test_declared_width_does_not_allocate_empty_columns(
    monkeypatch: pytest.MonkeyPatch,
    dimension: str | None,
) -> None:
    healthy = _workbook()
    expected = _parse_excel_contact_bytes(healthy, filename="synthetic.xlsx")
    payload = _dimension(healthy, dimension) if dimension else healthy
    slots: list[int] = []
    original = ReadOnlyWorksheet._get_row

    def counted_row(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        slots.append(len(result))
        return result

    monkeypatch.setattr(ReadOnlyWorksheet, "_get_row", counted_row)

    result = _parse_excel_contact_bytes(payload, filename="synthetic.xlsx")

    assert result == expected
    assert len(result.contacts) == 1
    assert sum(slots) <= 128


@pytest.mark.parametrize(
    "layout",
    ["standard", "given_surname", "headerless", "wide", "multisheet"],
)
@pytest.mark.parametrize("dimension", ["A1:A1", "A1:XFD64"])
def test_dimension_metadata_never_discards_or_invents_actual_contact_cells(
    layout: str,
    dimension: str,
) -> None:
    healthy = _workbook(layout=layout, rows=3)
    expected = _parse_excel_contact_bytes(healthy, filename="synthetic.xlsx")
    assert expected.contacts
    payload = _dimension(healthy, dimension)

    actual = _parse_excel_contact_bytes(payload, filename="synthetic.xlsx")

    assert actual == expected
    assert actual.contacts[0].name == "Synthetic Traveller"
    assert actual.contacts[0].phone_number
