"""
Get Passport Submission Use Case
================================
"""

from __future__ import annotations

import uuid

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.domain.repositories.interfaces import IPassportSubmissionRepository


class GetPassportSubmissionUseCase:
    def __init__(self, passport_repo: IPassportSubmissionRepository) -> None:
        self._passport_repo = passport_repo

    async def execute(self, submission_id: uuid.UUID) -> PassportSubmissionOutputDTO:
        submission = await self._passport_repo.get_by_id(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)

        return passport_submission_output_from_entity(submission)
