"""
Analytics Routes
================
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.passports.passport_analytics import GetPassportAnalyticsSummary
from app.domain.entities.entities import (
    User,
    UserRole,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_analytics_repository import (
    PassportAnalyticsRepository,
)
from app.presentation.api.v1.schemas.operations_schemas import AnalyticsSummaryResponse
from app.presentation.dependencies.auth import require_role

router = APIRouter()


@router.get(
    "/summary",
    response_model=AnalyticsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get passport processing analytics",
)
async def get_analytics_summary(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
    days: int = 30,
) -> AnalyticsSummaryResponse:
    projection, _since, _days = await GetPassportAnalyticsSummary(
        PassportAnalyticsRepository(session)
    ).execute(current_user, days)
    return AnalyticsSummaryResponse(**projection.project())
