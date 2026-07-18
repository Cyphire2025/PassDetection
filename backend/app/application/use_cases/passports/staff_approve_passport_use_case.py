"""Atomic staff correction and approval for post-submit passport review."""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.domain.entities.entities import StaffApprovalOutcome
from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.domain.repositories.interfaces import IPassportSubmissionRepository
from app.domain.value_objects.passport_fields import (
    normalize_reviewed_passport_fields,
    validate_reviewed_passport_payload,
)

MAX_STAFF_REVIEW_REASON_LENGTH = 240


@dataclass(frozen=True, slots=True)
class StaffApprovalResult:
    submission: PassportSubmissionOutputDTO
    outcome: StaffApprovalOutcome
    previous_status: str
    corrected_field_names: tuple[str, ...]
    review_reason: str | None


def normalize_staff_review_reason(reason: str | None) -> str | None:
    """Bound audit notes and remove control characters before persistence."""

    if reason is None:
        return None
    without_controls = "".join(
        " " if unicodedata.category(character).startswith("C") else character
        for character in reason
    )
    normalized = " ".join(without_controls.strip().split())
    if not normalized:
        return None
    if len(normalized) > MAX_STAFF_REVIEW_REASON_LENGTH:
        raise ValidationError(
            f"Review reason must be {MAX_STAFF_REVIEW_REASON_LENGTH} characters or fewer.",
            field="review_reason",
        )
    return normalized


class StaffApprovePassportUseCase:
    def __init__(self, passport_repo: IPassportSubmissionRepository) -> None:
        self._passport_repo = passport_repo

    async def execute(
        self,
        submission_id: uuid.UUID,
        *,
        reviewer_id: uuid.UUID,
        reviewer_name: str,
        expected_extraction_revision: int,
        confirmed_fields: dict[str, str] | None = None,
        review_reason: str | None = None,
    ) -> StaffApprovalResult:
        clean_corrections: dict[str, str] | None = None
        if confirmed_fields is not None:
            validate_reviewed_passport_payload(confirmed_fields)
            clean_corrections = normalize_reviewed_passport_fields(confirmed_fields)
            if not clean_corrections:
                raise ValidationError(
                    "At least one confirmed field is required.",
                    field="confirmed_fields",
                )
        clean_reason = normalize_staff_review_reason(review_reason)

        submission = await self._passport_repo.get_by_id_for_update(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)

        previous_status = submission.status.value
        previous_fields = dict(submission.confirmed_fields or {})
        corrected_field_names = tuple(
            sorted(
                key
                for key, value in (clean_corrections or {}).items()
                if previous_fields.get(key) != value
            )
        )
        outcome = submission.staff_approve_verification(
            reviewer_id=reviewer_id,
            reviewer_name=reviewer_name,
            confirmed_fields=clean_corrections,
            expected_extraction_revision=expected_extraction_revision,
        )
        if outcome is StaffApprovalOutcome.APPROVED:
            await self._passport_repo.update(submission)
        return StaffApprovalResult(
            submission=passport_submission_output_from_entity(submission),
            outcome=outcome,
            previous_status=previous_status,
            corrected_field_names=corrected_field_names,
            review_reason=clean_reason,
        )
