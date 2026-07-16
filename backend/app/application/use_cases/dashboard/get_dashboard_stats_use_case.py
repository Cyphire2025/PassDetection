"""
Get Dashboard Stats Use Case
============================
Fetches dashboard stats (totals, status breakdown, active links, recent activity)
for an agency or overall for super admin.
"""

from __future__ import annotations

import uuid

from app.application.dtos.dashboard_dtos import DashboardStatsDTO, RecentSubmissionDTO
from app.core.logging.logger import get_logger
from app.domain.entities.entities import PassportProcessingStatus, User
from app.domain.repositories.interfaces import IClientGroupRepository, IPassportSubmissionRepository

logger = get_logger(__name__)


class GetDashboardStatsUseCase:
    """Calculates dashboard metrics and gets recent submissions."""

    def __init__(
        self,
        submission_repository: IPassportSubmissionRepository,
        client_group_repository: IClientGroupRepository,
    ) -> None:
        self._submission_repo = submission_repository
        self._client_group_repo = client_group_repository

    async def execute(
        self,
        agency_id: uuid.UUID,
        *,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> DashboardStatsDTO:
        # Get count of total submissions
        total_passports = await self._submission_repo.count_by_agency(
            agency_id,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )

        # Get count of pending review submissions
        pending_review = await self._submission_repo.count_by_agency(
            agency_id,
            status_filter=PassportProcessingStatus.REVIEW_REQUIRED.value,
            exclude_archived_groups=True,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )

        # Get count of confirmed submissions
        confirmed = await self._submission_repo.count_by_agency(
            agency_id,
            status_filter=PassportProcessingStatus.CONFIRMED.value,
            exclude_archived_groups=True,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )

        # Get count of active upload links
        active_links = await self._client_group_repo.count_active_by_agency(
            agency_id,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )

        # Recent Activity should only show passports clients actually submitted after review.
        recent_list = await self._submission_repo.list_by_agency(
            agency_id,
            skip=0,
            limit=5,
            status_filter=PassportProcessingStatus.CLIENT_SUBMITTED.value,
            exclude_archived_groups=True,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )

        recent_submissions = [
            RecentSubmissionDTO(
                id=sub.id,
                client_name=sub.client_name,
                client_email=sub.client_email,
                status=sub.status.value,
                created_at=sub.created_at,
                overall_confidence=sub.overall_confidence,
            )
            for sub in recent_list
        ]

        logger.info("dashboard_stats_fetched", agency_id=str(agency_id))

        return DashboardStatsDTO(
            total_passports=total_passports,
            pending_review=pending_review,
            confirmed=confirmed,
            active_links=active_links,
            recent_submissions=recent_submissions,
        )
