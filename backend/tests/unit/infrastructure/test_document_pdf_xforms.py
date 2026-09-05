"""Real small PDF fixtures exercise the patched pypdf compatibility fallback."""

from __future__ import annotations

from io import BytesIO

import pypdf._page as pypdf_page
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from app.infrastructure.documents import document_matcher
from app.infrastructure.documents.document_matcher import DocumentMatcher


def _form_pdf(*, repetitions: int) -> bytes:
    """A tiny legitimate form hierarchy, never an unbounded or recursive file."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    fonts = DictionaryObject({NameObject("/F1"): font})

    def add_form(content: bytes, resources: DictionaryObject):
        form = DecodedStreamObject()
        form.set_data(content)
        form.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/FormType"): NumberObject(1),
                NameObject("/BBox"): ArrayObject([NumberObject(n) for n in (0, 0, 300, 300)]),
                NameObject("/Resources"): resources,
            }
        )
        return writer._add_object(form)

    leaf = add_form(
        b"BT /F1 12 Tf 10 200 Td (ELECTRONIC VISA) Tj ET",
        DictionaryObject({NameObject("/Font"): fonts}),
    )
    outer = add_form(
        b"/Leaf Do /Leaf Do /Leaf Do",
        DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Leaf"): leaf})}),
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): fonts,
            NameObject("/XObject"): DictionaryObject({NameObject("/Outer"): outer}),
        }
    )
    content = DecodedStreamObject()
    content.set_data(
        b"/Outer Do\n" * repetitions + b"BT /F1 12 Tf 10 100 Td (Passport number: P1234567) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_valid_nested_ticket_or_visa_forms_remain_readable_without_pdfium(monkeypatch):
    monkeypatch.setattr(document_matcher, "pypdfium2", None)
    content = _form_pdf(repetitions=1)

    result = DocumentMatcher()._read_pdf_text_with_pypdf(content)

    assert result.safe_for_ocr is True
    assert result.text.count("ELECTRONIC VISA") == 3
    assert "Passport number: P1234567" in result.text


def test_xform_limit_is_shared_across_nested_and_repeated_form_calls(monkeypatch, caplog):
    # Lower the library's cap only in this test, so a tiny benign fixture
    # exercises the production guard without a large or malicious PDF workload.
    monkeypatch.setattr(pypdf_page, "MAX_XFORM_INVOCATIONS_PER_EXTRACTION", 4)
    monkeypatch.setattr(document_matcher, "pypdfium2", None)
    content = _form_pdf(repetitions=6)

    result = DocumentMatcher()._read_pdf_text_with_pypdf(content)

    assert result.safe_for_ocr is True
    # One outer invocation and three leaf invocations consume the shared cap.
    assert result.text.count("ELECTRONIC VISA") == 3
    # Ordinary content following the forms is still inspected.
    assert "Passport number: P1234567" in result.text
    assert len(result.text) < 200
    limit_warnings = [
        record for record in caplog.records if "form XObject invocations" in record.getMessage()
    ]
    assert len(limit_warnings) == 1
