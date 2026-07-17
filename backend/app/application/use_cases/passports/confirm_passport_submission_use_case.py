"""
Confirm Passport Submission Use Case
===================================
"""

from __future__ import annotations

import uuid

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.domain.repositories.interfaces import IPassportSubmissionRepository
from app.domain.value_objects.passport_fields import normalize_reviewed_passport_fields


class ConfirmPassportSubmissionUseCase:
    def __init__(self, passport_repo: IPassportSubmissionRepository) -> None:
        self._passport_repo = passport_repo

    async def execute(
        self,
        submission_id: uuid.UUID,
        *,
        confirmed_fields: dict[str, str],
    ) -> PassportSubmissionOutputDTO:
        submission = await self._passport_repo.get_by_id_for_update(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)

        clean_fields = normalize_reviewed_passport_fields(confirmed_fields)

        if not clean_fields:
            raise ValidationError("At least one confirmed field is required", field="confirmed_fields")

        submission.confirm(clean_fields)
        await self._passport_repo.update(submission)

        return passport_submission_output_from_entity(submission)
