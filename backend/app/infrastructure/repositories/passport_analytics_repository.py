"""The website's three scalar analytics queries with optional MCP day admission."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import case, cast, func, select
from sqlalchemy.dialects.postgresql import DATE
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.domain.value_objects.passport_analytics import (
    PassportAnalyticsLimitError,
    PassportAnalyticsSummary,
)
from app.infrastructure.database.models import PassportSubmissionModel


class PassportAnalyticsRepository:
    def __init__(self, session: AsyncSession, *, maximum_day_groups: int | None = None):
        self.session, self.maximum_day_groups = session, maximum_day_groups

    async def aggregate(
        self, *, since: datetime, agency_id: UUID | None
    ) -> PassportAnalyticsSummary:
        model = PassportSubmissionModel
        filters = [
            model.created_at >= since,
            model.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        ]
        if agency_id is not None:
            filters.append(model.agency_id == agency_id)
        status_result = await self.session.execute(
            select(model.status, func.count()).where(*filters).group_by(model.status)
        )
        status_counts = {status: int(count) for status, count in status_result.all()}
        bucket_result = await self.session.execute(
            select(
                func.sum(case((model.overall_confidence >= 0.9, 1), else_=0)).label("high"),
                func.sum(case((model.overall_confidence.between(0.75, 0.899), 1), else_=0)).label(
                    "medium"
                ),
                func.sum(case((model.overall_confidence < 0.75, 1), else_=0)).label("low"),
                func.sum(case((model.overall_confidence.is_(None), 1), else_=0)).label("missing"),
                func.avg(model.overall_confidence).label("average"),
            ).where(*filters)
        )
        bucket = bucket_result.one()
        day = cast(model.created_at, DATE)
        query = select(day, func.count()).where(*filters).group_by(day).order_by(day)
        if self.maximum_day_groups is not None:
            query = query.limit(self.maximum_day_groups + 1)
        by_day = (await self.session.execute(query)).all()
        if self.maximum_day_groups is not None and len(by_day) > self.maximum_day_groups:
            raise PassportAnalyticsLimitError()
        return PassportAnalyticsSummary(
            status_counts=status_counts,
            confidence_buckets={
                "high": int(bucket.high or 0),
                "medium": int(bucket.medium or 0),
                "low": int(bucket.low or 0),
                "missing": int(bucket.missing or 0),
            },
            submissions_by_day={str(day): int(count) for day, count in by_day},
            average_confidence=round(float(bucket.average), 3)
            if bucket.average is not None
            else None,
        )
