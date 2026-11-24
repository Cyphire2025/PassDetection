"""Post submission result formatter."""

from __future__ import annotations

from typing import Any

from app.application.interfaces.post_submission_verification import (
    REQUIRED_POST_SUBMISSION_FIELDS,
    PostSubmissionFieldResult,
    PostSubmissionFieldVerdict,
    PostSubmissionVerificationDecision,
    PostSubmissionVerificationResult,
)
from app.infrastructure.ai.post_submission_document_policy import PostSubmissionDocumentAssessment
from app.infrastructure.ai.post_submission_field_policy import _normalize_passport_value


class PostSubmissionFormatterAgent:
    """Produce the bounded, deterministic response persisted and returned by the API."""

    def format(
        self,
        *,
        fields: tuple[PostSubmissionFieldResult, ...],
        decision: PostSubmissionVerificationDecision,
        document_assessment: PostSubmissionDocumentAssessment,
        submitted_fields: dict[str, Any],
        model: str,
    ) -> PostSubmissionVerificationResult:
        relevant = [
            result
            for result in fields
            if result.field in REQUIRED_POST_SUBMISSION_FIELDS
            or _normalize_passport_value(result.field, submitted_fields.get(result.field))
        ]
        confidence = (
            round(sum(result.confidence for result in relevant) / len(relevant), 4)
            if relevant
            else 0.0
        )
        confidence = min(
            confidence,
            document_assessment.classification_confidence,
        )
        incorrect_count = sum(
            result.verdict == PostSubmissionFieldVerdict.INCORRECT for result in fields
        )
        suspicious_count = sum(
            result.verdict == PostSubmissionFieldVerdict.SUSPICIOUS for result in fields
        )
        if decision == PostSubmissionVerificationDecision.AI_APPROVED:
            explanation = "All submitted passport fields matched the image."
        elif document_assessment.review_explanation is not None:
            explanation = document_assessment.review_explanation
        else:
            explanation = (
                f"{incorrect_count} incorrect and {suspicious_count} suspicious "
                "passport fields require staff review."
            )
        return PostSubmissionVerificationResult(
            decision=decision,
            confidence=confidence,
            explanation=explanation,
            provider_status="verified",
            reason_code=document_assessment.review_reason_code,
            model=model,
            fields=fields,
        )
