"""Application contract for the second, post-submit passport verification."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

POST_SUBMISSION_PASSPORT_FIELDS: Final[tuple[str, ...]] = (
    "surname",
    "given_names",
    "passport_number",
    "nationality",
    "place_of_issue",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
    "sex",
)

REQUIRED_POST_SUBMISSION_FIELDS: Final[frozenset[str]] = frozenset(
    field for field in POST_SUBMISSION_PASSPORT_FIELDS if field != "date_of_issue"
)


class PostSubmissionFieldVerdict(str, Enum):
    CORRECT = "correct"
    SUSPICIOUS = "suspicious"
    INCORRECT = "incorrect"


class PostSubmissionVerificationDecision(str, Enum):
    AI_APPROVED = "ai_approved"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class PostSubmissionFieldResult:
    field: str
    verdict: PostSubmissionFieldVerdict
    observed_value: str | None
    confidence: float
    reason_code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "verdict": self.verdict.value,
            "observed_value": self.observed_value,
            "confidence": self.confidence,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class PostSubmissionVerificationResult:
    decision: PostSubmissionVerificationDecision
    confidence: float
    explanation: str
    provider_status: str
    reason_code: str | None
    model: str | None
    fields: tuple[PostSubmissionFieldResult, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        incorrect_fields = [
            field.field
            for field in self.fields
            if field.verdict == PostSubmissionFieldVerdict.INCORRECT
        ]
        suspicious_fields = [
            field.field
            for field in self.fields
            if field.verdict == PostSubmissionFieldVerdict.SUSPICIOUS
        ]
        return {
            "verification_status": self.decision.value,
            "confidence": self.confidence,
            "incorrect_fields": incorrect_fields,
            "suspicious_fields": suspicious_fields,
            "explanation": self.explanation[:240],
            "provider_status": self.provider_status,
            "reason_code": self.reason_code,
            "model": self.model,
            "fields": [field.to_dict() for field in self.fields],
        }

    @classmethod
    def fallback(
        cls,
        *,
        provider_status: str,
        reason_code: str,
        model: str | None = None,
        submitted_fields: dict[str, Any] | None = None,
    ) -> PostSubmissionVerificationResult:
        fields = tuple(
            PostSubmissionFieldResult(
                field=field,
                verdict=PostSubmissionFieldVerdict.SUSPICIOUS,
                observed_value=None,
                confidence=0.0,
                reason_code=reason_code,
            )
            for field in POST_SUBMISSION_PASSPORT_FIELDS
        )
        return cls(
            decision=PostSubmissionVerificationDecision.NEEDS_REVIEW,
            confidence=0.0,
            explanation="AI verification was unavailable; staff review is required.",
            provider_status=provider_status,
            reason_code=reason_code,
            model=model,
            fields=fields,
        )


class IPostSubmissionPassportVerificationService(ABC):
    """Verify submitted client fields against the stored passport data page."""

    @abstractmethod
    async def verify(
        self,
        image_content: bytes,
        *,
        content_type: str,
        submitted_fields: dict[str, Any],
    ) -> PostSubmissionVerificationResult:
        """Return a conservative decision; provider failures must not raise."""
        ...
