"""
List Passport Submissions by Group Use Case
==========================================
"""

from __future__ import annotations

import uuid

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.domain.entities.entities import User
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
        limit: int | None = 100,
        search: str | None = None,
        created_by_user_id: uuid.UUID | None = None,
        include_deleted_group: bool = False,
        visible_to_user: User | None = None,
    ) -> list[PassportSubmissionOutputDTO]:
        submissions = await self._passport_repo.list_by_group(
            agency_id,
            group_id,
            skip=skip,
            limit=limit,
            search=search,
            exclude_archived_groups=not include_deleted_group,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )

        return [
            passport_submission_output_from_entity(submission)
            for submission in submissions
        ]
