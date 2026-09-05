"""Request-local work reduction must retain every input and filename contract."""

from unittest.mock import Mock

from app.infrastructure.documents.document_matcher import (
    DocumentMatcher,
    classify_documents_bounded,
)


def test_exact_duplicates_are_parsed_once_and_keep_original_order(monkeypatch):
    matcher = DocumentMatcher()
    read = Mock(return_value="Electronic visa\nPassport no: A1234567")
    monkeypatch.setattr(matcher, "_pdf_text", read)
    jobs = [
        ("visa.pdf", b"%PDF-one", "visa"),
        ("second.pdf", b"%PDF-two", "visa"),
        ("visa.pdf", b"%PDF-one", "visa"),
    ]
    result = classify_documents_bounded(matcher, jobs, isolate_pdf_parsing=False)
    assert read.call_count == 2
    assert [row.original_filename for row in result] == ["visa.pdf", "second.pdf", "visa.pdf"]
    assert result[0] == result[2]


def test_filename_and_expected_lane_are_distinct_even_for_identical_content(monkeypatch):
    matcher = DocumentMatcher()
    read = Mock(return_value="ELECTRONIC VISA\nPassport no: A1234567")
    monkeypatch.setattr(matcher, "_pdf_text", read)
    jobs = [
        ("visa.pdf", b"%PDF-one", "visa"),
        ("renamed.pdf", b"%PDF-one", "visa"),
        ("visa.pdf", b"%PDF-one", "flight_ticket"),
        ("visa.txt", b"%PDF-one", "visa"),
    ]
    result = classify_documents_bounded(matcher, jobs, isolate_pdf_parsing=False)
    assert read.call_count == 3
    assert [row.original_filename for row in result] == [row[0] for row in jobs]
    assert not result[-1].accepted
    assert result[-1].reason == "Only PDF files are accepted"


def test_empty_batch_never_starts_parser():
    assert classify_documents_bounded(DocumentMatcher(), [], isolate_pdf_parsing=True) == []
