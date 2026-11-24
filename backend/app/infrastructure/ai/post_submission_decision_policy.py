"""Post submission decision policy."""

from __future__ import annotations

from typing import Any

from app.application.interfaces.post_submission_verification import (
    POST_SUBMISSION_PASSPORT_FIELDS,
    REQUIRED_POST_SUBMISSION_FIELDS,
    PostSubmissionFieldResult,
    PostSubmissionFieldVerdict,
    PostSubmissionVerificationDecision,
)
from app.infrastructure.ai.post_submission_field_policy import _normalize_passport_value


class PostSubmissionConfidenceAgent:
    """Conservatively downgrade verdicts that lack sufficient visual confidence."""

    def calibrate(
        self,
        fields: tuple[PostSubmissionFieldResult, ...],
    ) -> tuple[PostSubmissionFieldResult, ...]:
        calibrated: list[PostSubmissionFieldResult] = []
        for result in fields:
            verdict = result.verdict
            reason_code = result.reason_code
            confidence = result.confidence
            if (result.observed_value is None and reason_code != "not_present") or reason_code in {
                "unreadable",
                "missing_submitted_value",
            }:
                confidence = 0.0
            if verdict == PostSubmissionFieldVerdict.CORRECT and confidence < 0.90:
                verdict = PostSubmissionFieldVerdict.SUSPICIOUS
                reason_code = "low_confidence"
            elif verdict == PostSubmissionFieldVerdict.INCORRECT and confidence < 0.75:
                verdict = PostSubmissionFieldVerdict.SUSPICIOUS
                reason_code = "low_confidence"
            calibrated.append(
                PostSubmissionFieldResult(
                    field=result.field,
                    verdict=verdict,
                    observed_value=result.observed_value,
                    confidence=round(confidence, 4),
                    reason_code=reason_code,
                )
            )
        return tuple(calibrated)


class PostSubmissionDecisionAgent:
    """Map calibrated field evidence to AI Approved or Needs Review."""

    def decide(
        self,
        fields: tuple[PostSubmissionFieldResult, ...],
        submitted_fields: dict[str, Any],
    ) -> PostSubmissionVerificationDecision:
        by_field = {field.field: field for field in fields}
        for field in REQUIRED_POST_SUBMISSION_FIELDS:
            submitted = _normalize_passport_value(
                field,
                submitted_fields.get(field),
            )
            result = by_field[field]
            if (
                field == "surname"
                and not submitted
                and result.verdict == PostSubmissionFieldVerdict.CORRECT
                and result.reason_code == "not_present"
            ):
                continue
            if not submitted:
                return PostSubmissionVerificationDecision.NEEDS_REVIEW
            if result.verdict != PostSubmissionFieldVerdict.CORRECT:
                return PostSubmissionVerificationDecision.NEEDS_REVIEW
        for field in POST_SUBMISSION_PASSPORT_FIELDS:
            if (
                _normalize_passport_value(field, submitted_fields.get(field))
                and by_field[field].verdict != PostSubmissionFieldVerdict.CORRECT
            ):
                return PostSubmissionVerificationDecision.NEEDS_REVIEW
        return PostSubmissionVerificationDecision.AI_APPROVED
