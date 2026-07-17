"""
List Passport Submissions Use Case
=================================
"""

from __future__ import annotations

import uuid

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.domain.entities.entities import User
from app.domain.repositories.interfaces import IPassportSubmissionRepository


class ListPassportSubmissionsUseCase:
    def __init__(self, passport_repo: IPassportSubmissionRepository) -> None:
        self._passport_repo = passport_repo

    async def execute(
        self,
        agency_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 100,
        status_filter: str | None = None,
        search: str | None = None,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[PassportSubmissionOutputDTO]:
        submissions = await self._passport_repo.list_by_agency(
            agency_id,
            skip=skip,
            limit=limit,
            status_filter=status_filter,
            search=search,
            exclude_archived_groups=True,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )

        return [
            passport_submission_output_from_entity(submission)
            for submission in submissions
        ]
