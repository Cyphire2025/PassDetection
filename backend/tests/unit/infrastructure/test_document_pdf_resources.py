"""Bound native PDF allocations before OCR and close resources on every path."""

from __future__ import annotations

import math
import sys
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.infrastructure.documents.document_matcher import _pdf_processing_limits
from app.infrastructure.documents.document_pdf_support import (
    DocumentOcrUnavailableError,
    _bounded_render_scale,
    _normalize_pdf_text,
    extract_pdf_text_with_pdfium,
    ocr_validated_image_only_pdf,
)


class Document:
    def __init__(self, page):
        self.page = page
        self.close = Mock()

    def __len__(self):
        return 1

    def __getitem__(self, index):
        assert index == 0
        return self.page


def test_equivalent_pdf_glyphs_preserve_identity_without_ocr_character_guesses():
    assert _normalize_pdf_text(
        "ＥＬＥＣＴＲＯＮＩＣ VISA\nPa\u00adssport: Ａ１２３４５６７\nﬂight\u200b number: ＡＩ １０１"
    ) == ("ELECTRONIC VISA\nPassport: A1234567\nflight number: AI 101")
    assert _normalize_pdf_text("O012I1B8") == "O012I1B8"


def test_huge_page_pixel_budget_is_applied_before_native_render():
    limits = _pdf_processing_limits()
    width, height = 100_000, 200_000
    scale = _bounded_render_scale(SimpleNamespace(get_size=lambda: (width, height)), limits)
    assert math.ceil(width * scale) * math.ceil(height * scale) <= limits.max_ocr_pixels
    assert scale < limits.ocr_render_scale


@pytest.mark.parametrize("dimensions", [(0, 100), (-1, 100), (math.inf, 100), (math.nan, 100)])
def test_invalid_pdf_geometry_is_rejected(dimensions):
    with pytest.raises(ValueError):
        _bounded_render_scale(
            SimpleNamespace(get_size=lambda: dimensions), _pdf_processing_limits()
        )


def test_text_extraction_bounds_native_read_and_closes_page_handles():
    text = SimpleNamespace(
        count_chars=lambda: 1_000_000, get_text_range=Mock(return_value="ticket"), close=Mock()
    )
    page = SimpleNamespace(get_textpage=lambda: text, close=Mock())
    document = Document(page)
    result = extract_pdf_text_with_pdfium(
        b"%PDF",
        pdfium=SimpleNamespace(PdfDocument=lambda _: document),
        deadline=time.monotonic() + 1,
        limits=replace(_pdf_processing_limits(), max_page_text_chars=500),
    )
    assert result == "ticket"
    text.get_text_range.assert_called_once_with(count=500)
    for resource in (text, page, document):
        resource.close.assert_called_once()


@pytest.mark.parametrize("timeout", [False, True])
def test_ocr_sparse_fallback_and_timeout_both_release_native_resources(monkeypatch, timeout):
    image = SimpleNamespace(close=Mock())
    bitmap = SimpleNamespace(to_pil=lambda: image, close=Mock())
    page = SimpleNamespace(
        get_size=lambda: (600, 900), render=Mock(return_value=bitmap), close=Mock()
    )
    document = Document(page)
    recognize = Mock(
        side_effect=RuntimeError("deadline")
        if timeout
        else ["  ", "ELECTRONIC VISA\nPassport: A1234567"]
    )
    monkeypatch.setitem(sys.modules, "pytesseract", SimpleNamespace(image_to_string=recognize))
    if timeout:
        with pytest.raises(DocumentOcrUnavailableError):
            ocr_validated_image_only_pdf(
                b"%PDF",
                pdfium=SimpleNamespace(PdfDocument=lambda _: document),
                limits=_pdf_processing_limits(),
            )
    else:
        result = ocr_validated_image_only_pdf(
            b"%PDF",
            pdfium=SimpleNamespace(PdfDocument=lambda _: document),
            limits=_pdf_processing_limits(),
        )
        assert "A1234567" in result
        assert [call.kwargs["config"] for call in recognize.call_args_list] == [
            "--oem 1 --psm 6",
            "--oem 1 --psm 11",
        ]
    for resource in (image, bitmap, page, document):
        resource.close.assert_called_once()
