from __future__ import annotations

from app.domain.value_objects.passport_document_classification import (
    is_accepted_passport_information_page,
    passport_document_classification,
)


def test_document_classification_accepts_only_positive_structured_results() -> None:
    assert is_accepted_passport_information_page(
        {"status": "verified", "available": True}
    )
    assert is_accepted_passport_information_page(
        {"status": "enhanced", "available": True}
    )
    assert not is_accepted_passport_information_page(
        {"status": "wrong_document", "available": False}
    )
    assert not is_accepted_passport_information_page(
        {"status": "verified", "available": False}
    )
    assert not is_accepted_passport_information_page(
        {"status": "verified", "available": 1}
    )
    assert not is_accepted_passport_information_page(None)


def test_document_classification_ignores_non_mapping_metadata() -> None:
    assert passport_document_classification(None) is None
    assert passport_document_classification({"ai_verification": "verified"}) is None
    assert passport_document_classification(
        {"ai_verification": {"status": "verified", "available": True}}
    ) == {"status": "verified", "available": True}
