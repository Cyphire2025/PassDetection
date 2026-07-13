"""
Dashboard Routes — /api/v1/dashboard
====================================
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.dashboard.get_dashboard_stats_use_case import GetDashboardStatsUseCase
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_submission_repository import PassportSubmissionRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.schemas.dashboard_schemas import DashboardStatsResponse
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()


def _get_dashboard_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> GetDashboardStatsUseCase:
    return GetDashboardStatsUseCase(
        submission_repository=PassportSubmissionRepository(session),
        client_group_repository=ClientGroupRepository(session),
    )


@router.get(
    "/stats",
    response_model=DashboardStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get dashboard statistics and recent activity",
)
async def get_dashboard_stats(
    current_user: User = Depends(get_current_active_user),
    use_case: GetDashboardStatsUseCase = Depends(_get_dashboard_use_case),
) -> DashboardStatsResponse:
    if not current_user.agency_id:
        # Default empty stats for super admin with no agency assigned yet
        return DashboardStatsResponse(
            total_passports=0,
            pending_review=0,
            confirmed=0,
            active_links=0,
            recent_submissions=[],
        )

    result = await use_case.execute(
        agency_id=current_user.agency_id,
        created_by_user_id=current_user.id if current_user.role == UserRole.AGENCY_STAFF else None,
        visible_to_user=current_user,
    )
    return DashboardStatsResponse(
        total_passports=result.total_passports,
        pending_review=result.pending_review,
        confirmed=result.confirmed,
        active_links=result.active_links,
        recent_submissions=[
            {
                "id": sub.id,
                "client_name": sub.client_name,
                "client_email": sub.client_email,
                "status": sub.status,
                "created_at": sub.created_at,
                "overall_confidence": sub.overall_confidence,
            }
            for sub in result.recent_submissions
        ],
    )
