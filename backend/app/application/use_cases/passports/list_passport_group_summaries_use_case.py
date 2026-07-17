"""
List Passport Group Summaries Use Case
=====================================
"""

from __future__ import annotations

import uuid

from app.application.dtos.passport_dtos import PassportGroupSummaryDTO
from app.domain.entities.entities import User
from app.domain.repositories.interfaces import IPassportSubmissionRepository


class ListPassportGroupSummariesUseCase:
    """Lists client groups that contain at least one passport submission."""

    def __init__(self, passport_repo: IPassportSubmissionRepository) -> None:
        self._passport_repo = passport_repo

    async def execute(
        self,
        agency_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[PassportGroupSummaryDTO]:
        summaries = await self._passport_repo.list_group_summaries_by_agency(
            agency_id,
            skip=skip,
            limit=limit,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )

        return [
            PassportGroupSummaryDTO(
                group_id=summary.group_id,
                group_name=summary.group_name,
                group_status=summary.group_status,
                total_passports=summary.total_passports,
                pending_review_count=summary.pending_review_count,
                confirmed_count=summary.confirmed_count,
                failed_count=summary.failed_count,
                latest_submission_at=summary.latest_submission_at,
                destination=summary.destination,
                travel_date=summary.travel_date,
                return_date=summary.return_date,
                package_name=summary.package_name,
                departure_cities=list(summary.departure_cities or []),
                base_city_enabled=summary.base_city_enabled,
                nearest_international_airport_enabled=summary.nearest_international_airport_enabled,
                staff_code_enabled=summary.staff_code_enabled,
                meal_preference_enabled=summary.meal_preference_enabled,
                require_selfie=summary.require_selfie,
                notes=summary.notes,
            )
            for summary in summaries
        ]
