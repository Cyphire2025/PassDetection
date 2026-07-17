"""Atomic staff correction and approval for post-submit passport review."""

from __future__ import annotations

import uuid

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.domain.repositories.interfaces import IPassportSubmissionRepository
from app.domain.value_objects.passport_fields import (
    normalize_reviewed_passport_fields,
    validate_reviewed_passport_payload,
)


class StaffApprovePassportUseCase:
    def __init__(self, passport_repo: IPassportSubmissionRepository) -> None:
        self._passport_repo = passport_repo

    async def execute(
        self,
        submission_id: uuid.UUID,
        *,
        reviewer_id: uuid.UUID,
        reviewer_name: str,
        confirmed_fields: dict[str, str] | None = None,
    ) -> tuple[PassportSubmissionOutputDTO, bool]:
        submission = await self._passport_repo.get_by_id_for_update(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)

        clean_fields: dict[str, str] | None = None
        if confirmed_fields is not None:
            validate_reviewed_passport_payload(confirmed_fields)
            clean_corrections = normalize_reviewed_passport_fields(confirmed_fields)
            if not clean_corrections:
                raise ValidationError(
                    "At least one confirmed field is required.",
                    field="confirmed_fields",
                )
            clean_fields = {
                **dict(submission.confirmed_fields or {}),
                **clean_corrections,
            }

        changed = submission.staff_approve_verification(
            reviewer_id=reviewer_id,
            reviewer_name=reviewer_name,
            confirmed_fields=clean_fields,
        )
        if changed:
            await self._passport_repo.update(submission)
        return passport_submission_output_from_entity(submission), changed
