"""Canonical lower-bound rolling window and role scope for passport analytics."""

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.domain.entities.entities import User, UserRole
from app.domain.value_objects.passport_analytics import PassportAnalyticsSummary


class PassportAnalyticsReader(Protocol):
    async def aggregate(
        self, *, since: datetime, agency_id: UUID | None
    ) -> PassportAnalyticsSummary: ...


class GetPassportAnalyticsSummary:
    def __init__(self, reader: PassportAnalyticsReader):
        self.reader = reader

    async def execute(
        self, actor: User, days: int = 30, *, now: datetime | None = None
    ) -> tuple[PassportAnalyticsSummary, datetime, int]:
        bounded_days = max(1, min(days, 365))
        since = (now or datetime.now(UTC)) - timedelta(days=bounded_days)
        if actor.role != UserRole.SUPER_ADMIN and not actor.agency_id:
            return PassportAnalyticsSummary({}, {}, {}, None), since, bounded_days
        agency_id = None if actor.role == UserRole.SUPER_ADMIN else actor.agency_id
        return await self.reader.aggregate(since=since, agency_id=agency_id), since, bounded_days
