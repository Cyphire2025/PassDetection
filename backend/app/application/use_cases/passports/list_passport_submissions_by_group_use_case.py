"""
List Passport Submissions by Group Use Case
==========================================
"""

from __future__ import annotations

import uuid

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.domain.repositories.interfaces import IPassportSubmissionRepository


class ListPassportSubmissionsByGroupUseCase:
    """Lists passport submissions for a specific client group."""

    def __init__(self, passport_repo: IPassportSubmissionRepository) -> None:
        self._passport_repo = passport_repo

    async def execute(
        self,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 100,
        search: str | None = None,
        created_by_user_id: uuid.UUID | None = None,
        include_deleted_group: bool = False,
    ) -> list[PassportSubmissionOutputDTO]:
        submissions = await self._passport_repo.list_by_group(
            agency_id,
            group_id,
            skip=skip,
            limit=limit,
            search=search,
            exclude_archived_groups=not include_deleted_group,
            created_by_user_id=created_by_user_id,
        )

        return [
            PassportSubmissionOutputDTO(
                id=submission.id,
                group_id=submission.group_id,
                agency_id=submission.agency_id,
                client_name=submission.client_name,
                client_email=submission.client_email,
                client_phone=submission.client_phone,
                image_s3_key=submission.image_s3_key,
                thumbnail_s3_key=submission.thumbnail_s3_key,
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
            for submission in submissions
        ]
