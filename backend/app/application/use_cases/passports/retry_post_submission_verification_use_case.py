"""Request a fresh AI verification after a temporary provider failure."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.domain.repositories.interfaces import IPassportSubmissionRepository


@dataclass(frozen=True)
class RetryPostSubmissionVerificationResult:
    submission: PassportSubmissionOutputDTO
    previous_provider_status: str
    previous_reason_code: str | None


class RetryPostSubmissionVerificationUseCase:
    """Start a new immutable verification revision without changing client fields."""

    def __init__(self, passport_repo: IPassportSubmissionRepository) -> None:
        self._passport_repo = passport_repo

    async def execute(
        self,
        submission_id: uuid.UUID,
    ) -> RetryPostSubmissionVerificationResult:
        submission = await self._passport_repo.get_by_id_for_update(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)

        verification = (
            submission.post_submission_verification
            if isinstance(submission.post_submission_verification, dict)
            else {}
        )
        previous_provider_status = str(
            verification.get("provider_status", "")
        ).strip().lower()
        raw_reason_code = verification.get("reason_code")
        previous_reason_code = (
            str(raw_reason_code).strip()[:80] if raw_reason_code else None
        )

        submission.request_post_submission_verification_retry()
        await self._passport_repo.update(submission)
        return RetryPostSubmissionVerificationResult(
            submission=passport_submission_output_from_entity(submission),
            previous_provider_status=previous_provider_status,
            previous_reason_code=previous_reason_code,
        )
