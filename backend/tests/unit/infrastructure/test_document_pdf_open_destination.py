"""Synthetic visa PDFs distinguish passive opening views from active content."""

from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NullObject,
    NumberObject,
    TextStringObject,
)

from app.infrastructure.documents import document_matcher
from app.infrastructure.documents.document_matcher import DocumentMatcher


def _visa_writer() -> PdfWriter:
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        }
    )
    lines = (
        "Electronic Visa on Arrival",
        "Directorate General of Immigration",
        "Full name: ASHA MEHTA",
        "Passport No.: P1234567",
        "Visa No.: V9876543",
        "Date of issue: 14/11/2026",
        "Duration of Stay: 30 DAY",
    )
    contents = DecodedStreamObject()
    contents.set_data(
        (
            "BT /F1 12 Tf 40 750 Td 20 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
        ).encode("ascii")
    )
    page[NameObject("/Contents")] = writer._add_object(contents)
    return writer


def _pdf_bytes(writer: PdfWriter) -> bytes:
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _opening_view(writer: PdfWriter, view="/XYZ", operands=None) -> ArrayObject:
    if operands is None:
        operands = [NullObject(), NullObject(), NumberObject(1)]
    return ArrayObject([writer.pages[0].indirect_reference, NameObject(view), *operands])


@pytest.mark.parametrize("use_pdfium", [True, False])
def test_indonesian_evoa_opening_view_reaches_visa_classification(monkeypatch, use_pdfium):
    if not use_pdfium:
        monkeypatch.setattr(document_matcher, "pypdfium2", None)
    writer = _visa_writer()
    writer.root_object[NameObject("/OpenAction")] = _opening_view(writer)

    result = DocumentMatcher().classify(
        filename="document.pdf",
        content=_pdf_bytes(writer),
        expected_type="visa",
    )

    assert result.accepted is True
    assert result.detected_type == "visa"
    assert result.extracted_passport_number == "P1234567"
    assert "Electronic Visa on Arrival" in result.text


@pytest.mark.parametrize(
    "view,operands",
    [
        ("/XYZ", [NullObject(), NullObject(), NumberObject(1)]),
        ("/XYZ", [NumberObject(0), NumberObject(800), FloatObject(1.25)]),
        ("/XYZ", [NullObject(), NullObject(), NumberObject(0)]),
        ("/XYZ", [NullObject(), NullObject(), NullObject()]),
        ("/Fit", []),
        ("/FitH", [NumberObject(800)]),
        ("/FitV", [NullObject()]),
        ("/FitR", [NumberObject(n) for n in (0, 0, 600, 800)]),
        ("/FitB", []),
        ("/FitBH", [NullObject()]),
        ("/FitBV", [NumberObject(0)]),
    ],
)
def test_passive_local_opening_destinations_are_accepted(view, operands):
    writer = _visa_writer()
    writer.root_object[NameObject("/OpenAction")] = _opening_view(writer, view, operands)

    reader = PdfReader(BytesIO(_pdf_bytes(writer)))

    assert DocumentMatcher()._has_active_pdf_features(reader) is False


def test_indirect_opening_destination_can_refer_to_another_local_page():
    writer = _visa_writer()
    page = writer.add_blank_page(width=600, height=800)
    destination = ArrayObject([page.indirect_reference, NameObject("/Fit")])
    writer.root_object[NameObject("/OpenAction")] = writer._add_object(destination)

    assert (
        DocumentMatcher()._has_active_pdf_features(PdfReader(BytesIO(_pdf_bytes(writer)))) is False
    )


@pytest.mark.parametrize(
    "view,operands",
    [
        ("/XYZ", []),
        ("/XYZ", [NullObject(), NullObject()]),
        ("/XYZ", [NullObject(), NullObject(), NumberObject(1), DictionaryObject()]),
        ("/XYZ", [TextStringObject("execute"), NullObject(), NumberObject(1)]),
        ("/XYZ", [BooleanObject(True), NullObject(), NumberObject(1)]),
        ("/XYZ", [NullObject(), NullObject(), NumberObject(-1)]),
        (
            "/XYZ",
            [
                DictionaryObject({NameObject("/JS"): TextStringObject("blocked")}),
                NullObject(),
                NumberObject(1),
            ],
        ),
        ("/Fit", [NumberObject(1)]),
        ("/FitH", []),
        ("/FitR", [NullObject(), NumberObject(0), NumberObject(600), NumberObject(800)]),
        ("/Launch", []),
    ],
)
def test_malformed_opening_destinations_remain_rejected(view, operands):
    writer = _visa_writer()
    writer.root_object[NameObject("/OpenAction")] = _opening_view(writer, view, operands)

    result = DocumentMatcher().classify(
        filename="visa.pdf",
        content=_pdf_bytes(writer),
        expected_type="visa",
    )

    assert result.accepted is False
    assert result.text == ""
    assert result.manual_review_allowed is False


@pytest.mark.parametrize("target", ["page-number", "orphan-page", "non-page-object"])
def test_opening_destination_must_reference_a_page_in_this_document(target):
    writer = _visa_writer()
    if target == "page-number":
        reference = NumberObject(0)
    else:
        value = DictionaryObject()
        if target == "orphan-page":
            value[NameObject("/Type")] = NameObject("/Page")
        reference = writer._add_object(value)
    writer.root_object[NameObject("/OpenAction")] = ArrayObject([reference, NameObject("/Fit")])

    assert (
        DocumentMatcher()._has_active_pdf_features(PdfReader(BytesIO(_pdf_bytes(writer)))) is True
    )


@pytest.mark.parametrize(
    "action_type",
    [
        "/JavaScript",
        "/Launch",
        "/SubmitForm",
        "/GoToR",
        "/URI",
        "/GoTo",
    ],
)
def test_opening_action_dictionaries_remain_rejected(action_type):
    writer = _visa_writer()
    writer.root_object[NameObject("/OpenAction")] = DictionaryObject(
        {
            NameObject("/S"): NameObject(action_type),
        }
    )

    assert (
        DocumentMatcher()._has_active_pdf_features(PdfReader(BytesIO(_pdf_bytes(writer)))) is True
    )


@pytest.mark.parametrize(
    "value",
    [
        TextStringObject("page1"),
        TextStringObject("/Fit"),
        NullObject(),
        ArrayObject(),
    ],
)
def test_unknown_opening_destination_values_remain_rejected(value):
    writer = _visa_writer()
    writer.root_object[NameObject("/OpenAction")] = value

    assert (
        DocumentMatcher()._has_active_pdf_features(PdfReader(BytesIO(_pdf_bytes(writer)))) is True
    )


@pytest.mark.parametrize(
    "active_feature", ["javascript", "attachment", "page-action", "link-action"]
)
def test_passive_opening_view_does_not_bypass_other_active_content_checks(active_feature):
    writer = _visa_writer()
    writer.root_object[NameObject("/OpenAction")] = _opening_view(writer)
    if active_feature == "javascript":
        writer.add_js("app.alert('blocked')")
    elif active_feature == "attachment":
        writer.add_attachment("payload.txt", b"blocked")
    elif active_feature == "page-action":
        writer.pages[0][NameObject("/AA")] = DictionaryObject()
    else:
        writer.pages[0][NameObject("/Annots")] = ArrayObject(
            [
                writer._add_object(
                    DictionaryObject(
                        {
                            NameObject("/Subtype"): NameObject("/Link"),
                            NameObject("/A"): DictionaryObject(
                                {
                                    NameObject("/S"): NameObject("/JavaScript"),
                                    NameObject("/JS"): TextStringObject("app.alert('blocked')"),
                                }
                            ),
                        }
                    )
                )
            ]
        )

    result = DocumentMatcher().classify(
        filename="visa.pdf",
        content=_pdf_bytes(writer),
        expected_type="visa",
    )

    assert result.accepted is False
    assert result.text == ""
    assert result.manual_review_allowed is False


def test_opening_view_without_visa_content_does_not_establish_document_type():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.root_object[NameObject("/OpenAction")] = _opening_view(writer)

    result = DocumentMatcher().classify(
        filename="visa.pdf",
        content=_pdf_bytes(writer),
        expected_type="visa",
    )

    assert result.accepted is False
    assert result.detected_type == "unknown"
