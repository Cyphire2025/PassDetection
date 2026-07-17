"""
Analytics Routes
================
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, status
from sqlalchemy import case, cast, func, select
from sqlalchemy.dialects.postgresql import DATE
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.session import get_db_session
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
    since = datetime.now(tz=UTC) - timedelta(days=max(1, min(days, 365)))
    base_filters = [
        PassportSubmissionModel.created_at >= since,
        PassportSubmissionModel.status.in_(("client_submitted", "confirmed")),
    ]
    if current_user.role != UserRole.SUPER_ADMIN:
        if not current_user.agency_id:
            return AnalyticsSummaryResponse(status_counts={}, confidence_buckets={}, submissions_by_day={}, average_confidence=None)
        base_filters.append(PassportSubmissionModel.agency_id == current_user.agency_id)

    status_result = await session.execute(
        select(PassportSubmissionModel.status, func.count())
        .where(*base_filters)
        .group_by(PassportSubmissionModel.status)
    )
    status_counts = {status: int(count) for status, count in status_result.all()}

    bucket_result = await session.execute(
        select(
            func.sum(case((PassportSubmissionModel.overall_confidence >= 0.9, 1), else_=0)).label("high"),
            func.sum(case((PassportSubmissionModel.overall_confidence.between(0.75, 0.899), 1), else_=0)).label("medium"),
            func.sum(case((PassportSubmissionModel.overall_confidence < 0.75, 1), else_=0)).label("low"),
            func.sum(case((PassportSubmissionModel.overall_confidence.is_(None), 1), else_=0)).label("missing"),
            func.avg(PassportSubmissionModel.overall_confidence).label("average"),
        ).where(*base_filters)
    )
    bucket_row = bucket_result.one()

    by_day_result = await session.execute(
        select(cast(PassportSubmissionModel.created_at, DATE), func.count())
        .where(*base_filters)
        .group_by(cast(PassportSubmissionModel.created_at, DATE))
        .order_by(cast(PassportSubmissionModel.created_at, DATE))
    )
    submissions_by_day = {str(day): int(count) for day, count in by_day_result.all()}

    return AnalyticsSummaryResponse(
        status_counts=status_counts,
        confidence_buckets={
            "high": int(bucket_row.high or 0),
            "medium": int(bucket_row.medium or 0),
            "low": int(bucket_row.low or 0),
            "missing": int(bucket_row.missing or 0),
        },
        submissions_by_day=submissions_by_day,
        average_confidence=round(float(bucket_row.average), 3) if bucket_row.average is not None else None,
    )
