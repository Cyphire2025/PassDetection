"""Real OpenXML namespace and stream boundaries cannot promote formula caches."""

import re
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook, load_workbook

from app.infrastructure.imports.passport_excel_importer import PassportExcelImporter

_NAMESPACE = b"http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_CACHED_PASSPORT = "P7654321"


def _cached_formula_workbook(prefix_length, tag_offset):
    workbook = Workbook()
    workbook.active.append(["Name", "Passport Number"])
    workbook.active.append(["Synthetic Traveller", "plain placeholder"])
    output = BytesIO()
    try:
        workbook.save(output)
    finally:
        workbook.close()
    with ZipFile(BytesIO(output.getvalue())) as archive:
        parts = {item.filename: archive.read(item) for item in archive.infolist()}
    xml = parts["xl/worksheets/sheet1.xml"]
    prefix = b"p" * prefix_length
    if prefix:
        xml = xml.replace(
            b"<worksheet ", b"<worksheet xmlns:" + prefix + b'="' + _NAMESPACE + b'" ', 1
        )
    original = re.search(rb'<c\b[^>]*\br="B2"[^>]*>.*?</c>', xml, re.DOTALL)
    assert original is not None
    opening = b"<" + (prefix + b":" if prefix else b"") + b"f>"
    closing = b"</" + (prefix + b":" if prefix else b"") + b"f>"
    before = xml[: original.start()] + b'<c r="B2" t="str">'
    padding = tag_offset - len(before) - len(b"<!---->")
    assert padding > 0
    cell = (
        before
        + b"<!--"
        + b" " * padding
        + b"-->"
        + opening
        + b'"P7654321"'
        + closing
        + b"<v>P7654321</v></c>"
    )
    parts["xl/worksheets/sheet1.xml"] = cell + xml[original.end() :]
    assert parts["xl/worksheets/sheet1.xml"].index(opening) == tag_offset
    result = BytesIO()
    with ZipFile(result, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    return result.getvalue()


@pytest.mark.parametrize(
    "prefix_length,tag_offset", [(0, 65_535), (32, 65_520), (256, 65_386), (2_048, 65_386)]
)
def test_valid_namespaced_formula_crossing_read_boundary_never_becomes_identity(
    prefix_length, tag_offset
):
    content = _cached_formula_workbook(prefix_length, tag_offset)
    # Prove the fixture is genuine cached-formula OpenXML accepted by the
    # installed SDK, rather than relying on a mocked cell or XML detector.
    cached, formulas = None, None
    try:
        cached = load_workbook(BytesIO(content), read_only=True, data_only=True)
        formulas = load_workbook(BytesIO(content), read_only=True, data_only=False)
        assert cached.active["B2"].value == _CACHED_PASSPORT
        assert formulas.active["B2"].data_type == "f"
    finally:
        if cached is not None:
            cached.close()
        if formulas is not None:
            formulas.close()
    importer = PassportExcelImporter()
    rows = importer.import_rows(content)
    assert len(rows) == 1 and rows[0].client_name == "Synthetic Traveller"
    assert "passport_number" not in rows[0].confirmed_fields
    assert "passport_number" not in rows[0].staff_metadata
    assert importer._validate_archive(content) is True
