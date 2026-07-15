"""
Confirm Passport Submission Use Case
===================================
"""

from __future__ import annotations

import uuid

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.domain.repositories.interfaces import IPassportSubmissionRepository


class ConfirmPassportSubmissionUseCase:
    def __init__(self, passport_repo: IPassportSubmissionRepository) -> None:
        self._passport_repo = passport_repo

    async def execute(
        self,
        submission_id: uuid.UUID,
        *,
        confirmed_fields: dict[str, str],
    ) -> PassportSubmissionOutputDTO:
        submission = await self._passport_repo.get_by_id(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)

        clean_fields = {
            key: value.strip()
            for key, value in confirmed_fields.items()
            if isinstance(value, str) and value.strip()
        }

        if not clean_fields:
            raise ValidationError("At least one confirmed field is required", field="confirmed_fields")

        submission.confirm(clean_fields)
        await self._passport_repo.update(submission)

        return PassportSubmissionOutputDTO(
            id=submission.id,
            group_id=submission.group_id,
            agency_id=submission.agency_id,
            client_name=submission.client_name,
            client_email=submission.client_email,
            client_phone=submission.client_phone,
            departure_city=submission.departure_city,
            submission_mode=submission.submission_mode,
            family_group_id=submission.family_group_id,
            family_member_index=submission.family_member_index,
            family_relation=submission.family_relation,
            family_gender=submission.family_gender,
            family_head_name=submission.family_head_name,
            family_head_email=submission.family_head_email,
            family_head_phone=submission.family_head_phone,
            family_broadcast_to_member=submission.family_broadcast_to_member,
            image_s3_key=submission.image_s3_key,
            thumbnail_s3_key=submission.thumbnail_s3_key,
            passport_photo_s3_key=submission.passport_photo_s3_key,
            passport_back_s3_key=submission.passport_back_s3_key,
            status=submission.status.value,
            created_at=submission.created_at,
            updated_at=submission.updated_at,
            extracted_fields=submission.extracted_fields,
            confirmed_fields=submission.confirmed_fields,
            overall_confidence=submission.overall_confidence,
            confidence_score=submission.confidence_score,
            mrz_raw=submission.mrz_raw,
            error_message=submission.error_message,
            client_reviewed_at=submission.client_reviewed_at,
            confirmed_at=submission.confirmed_at,
        )
