"""Post submission document policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.infrastructure.ai.post_submission_contract import (
    _DOCUMENT_CLASSES,
    _DOCUMENT_REASON_CODES,
    _DOCUMENT_REVIEW_EXPLANATIONS,
    _IMAGE_QUALITY_STATUSES,
    _PAGE_TYPES,
)


@dataclass(frozen=True)
class PostSubmissionDocumentAssessment:
    """Strict provider evidence plus an application-owned review outcome."""

    document_class: str
    page_type: str
    image_quality: str
    classification_confidence: float
    provider_reason_code: str
    review_reason_code: str | None

    @property
    def requires_review(self) -> bool:
        return self.review_reason_code is not None

    @property
    def review_explanation(self) -> str | None:
        if self.review_reason_code is None:
            return None
        return _DOCUMENT_REVIEW_EXPLANATIONS[self.review_reason_code]


class PostSubmissionDocumentAgent:
    """Validate document evidence and derive a conservative deterministic gate."""

    def evaluate(self, raw: Any) -> PostSubmissionDocumentAssessment:
        expected_keys = {
            "document_class",
            "page_type",
            "image_quality",
            "classification_confidence",
            "reason_code",
        }
        if not isinstance(raw, dict) or set(raw) != expected_keys:
            raise ValueError("Unexpected post-submission document result shape")

        document_class = raw["document_class"]
        page_type = raw["page_type"]
        image_quality = raw["image_quality"]
        provider_reason_code = raw["reason_code"]
        raw_confidence = raw["classification_confidence"]
        if (
            document_class not in _DOCUMENT_CLASSES
            or page_type not in _PAGE_TYPES
            or image_quality not in _IMAGE_QUALITY_STATUSES
            or provider_reason_code not in _DOCUMENT_REASON_CODES
            or isinstance(raw_confidence, bool)
            or not isinstance(raw_confidence, (int, float))
        ):
            raise ValueError("Unexpected post-submission document classification")

        classification_confidence = float(raw_confidence)
        if not 0.0 <= classification_confidence <= 1.0:
            raise ValueError("Document confidence must be between zero and one")

        review_reason_code = self._review_reason_code(
            document_class=str(document_class),
            page_type=str(page_type),
            image_quality=str(image_quality),
            classification_confidence=classification_confidence,
            provider_reason_code=str(provider_reason_code),
        )
        return PostSubmissionDocumentAssessment(
            document_class=str(document_class),
            page_type=str(page_type),
            image_quality=str(image_quality),
            classification_confidence=round(classification_confidence, 4),
            provider_reason_code=str(provider_reason_code),
            review_reason_code=review_reason_code,
        )

    @staticmethod
    def _review_reason_code(
        *,
        document_class: str,
        page_type: str,
        image_quality: str,
        classification_confidence: float,
        provider_reason_code: str,
    ) -> str | None:
        # Image quality is independently observable and blocks field approval
        # even when the model also proposes a document class.
        if image_quality == "unreadable":
            return "document_unreadable"
        if image_quality == "low_quality":
            return "document_low_quality"

        if document_class == "passport_cover" or page_type == "cover":
            return "passport_cover" if classification_confidence >= 0.75 else "document_uncertain"
        if document_class == "passport_other_page" or page_type == "other_passport_page":
            return (
                "wrong_passport_page" if classification_confidence >= 0.75 else "document_uncertain"
            )
        if document_class in {
            "aadhaar",
            "pan",
            "other_document",
            "not_document",
        }:
            return "wrong_document" if classification_confidence >= 0.80 else "document_uncertain"
        if (
            document_class == "passport_data_page"
            and page_type == "data_page"
            and classification_confidence >= 0.70
            and provider_reason_code == "passport_confirmed"
        ):
            return None
        return "document_uncertain"
