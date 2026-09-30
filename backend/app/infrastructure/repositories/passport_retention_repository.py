"""Bounded scalar schedule lookup using the existing administrative scope."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.group_passport_retention import PassportRetentionSchedule
from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import ClientGroupModel


class PassportRetentionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_schedule(
        self,
        *,
        group_id: UUID,
        role: UserRole,
        agency_id: UUID | None,
        shared_lock: bool = False,
    ) -> PassportRetentionSchedule | None:
        model = ClientGroupModel
        statement = select(
            model.id,
            model.agency_id,
            model.passport_purge_at,
            model.passport_retention_days_applied,
        ).where(model.id == group_id)
        # Preserve the website's Superadmin global and other-role IS NULL/own
        # agency predicates. Retained groups and inactive agencies stay visible.
        if role != UserRole.SUPER_ADMIN:
            statement = statement.where(model.agency_id == agency_id)
        if shared_lock:
            statement = statement.with_for_update(read=True, of=model)
        row = (await self.session.execute(statement)).one_or_none()
        return PassportRetentionSchedule(*row) if row is not None else None
