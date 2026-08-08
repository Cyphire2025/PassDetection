from pathlib import Path

from app.infrastructure.documents import (
    document_matcher,
    document_matcher_rules,
    document_pdf_support,
)


def test_document_matcher_reexports_rule_configuration() -> None:
    rule_names = (
        "MAX_PASSENGER_IDENTIFIERS",
        "MAX_PDF_OCR_SECONDS",
        "PDF_OCR_RENDER_SCALE",
        "PDF_OCR_RETRY_REASON",
        "PASSPORT_TERMS",
        "TICKET_CORE_TERMS",
        "VISA_CORE_TERMS",
        "VISA_IDENTITY_TERMS",
        "_NON_TRAVEL_DOCUMENT_PATTERNS",
    )

    for name in rule_names:
        assert getattr(document_matcher, name) is getattr(document_matcher_rules, name)


def test_matcher_implementation_does_not_duplicate_rule_vocabularies() -> None:
    matcher_source = Path(document_matcher.__file__).read_text(encoding="utf-8")

    assert "document_matcher_rules import" in matcher_source
    assert "VISA_CORE_TERMS = (" not in matcher_source
    assert "TICKET_CORE_TERMS = (" not in matcher_source
    assert "_NON_TRAVEL_DOCUMENT_PATTERNS = (" not in matcher_source


def test_pdf_parsing_lives_behind_compatibility_wrappers() -> None:
    matcher_source = Path(document_matcher.__file__).read_text(encoding="utf-8")
    pdf_support_source = Path(document_pdf_support.__file__).read_text(encoding="utf-8")

    assert "_pdf_support.read_pdf_text_with_pypdf(" in matcher_source
    assert "_pdf_support.has_active_pdf_features(" in matcher_source
    assert "def read_pdf_text_with_pypdf(" in pdf_support_source
    assert "def has_active_pdf_features(" in pdf_support_source
    assert "pytesseract.image_to_string(" not in matcher_source
