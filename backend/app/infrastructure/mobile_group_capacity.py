"""Concurrency-safe enforcement of the published per-group passenger quota."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel


class SqlAlchemyGroupPassengerCapacityGuard:
    """Use the tenant-owned group row as the short creation serialization lock."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_group(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> None:
        locked_group_id = await self._session.scalar(
            select(ClientGroupModel.id)
            .where(
                ClientGroupModel.id == group_id,
                ClientGroupModel.agency_id == agency_id,
                ClientGroupModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if locked_group_id is None:
            raise EntityNotFoundError("ClientGroup", group_id)

    async def assert_available(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        additional_passengers: int,
    ) -> None:
        if additional_passengers < 0:
            raise ValueError("additional_passengers must be non-negative")

        current = int(
            await self._session.scalar(
                select(func.count(PassportSubmissionModel.id)).where(
                    PassportSubmissionModel.agency_id == agency_id,
                    PassportSubmissionModel.group_id == group_id,
                )
            )
            or 0
        )
        maximum = get_settings().mobile.max_group_passengers
        if current + additional_passengers > maximum:
            raise ValidationError(
                (
                    f"This group supports at most {maximum:,} passenger records. "
                    "Remove an existing passenger or ask an administrator to review "
                    "the deployed mobile capacity before adding more."
                ),
                field="group_capacity",
            )


__all__ = ["SqlAlchemyGroupPassengerCapacityGuard"]
