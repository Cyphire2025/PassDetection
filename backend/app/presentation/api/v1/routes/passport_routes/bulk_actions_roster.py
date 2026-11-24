"""Bulk passport roster: focused scope, mutation or transaction owner."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.infrastructure.database.models import (
    PassportRosterResolutionModel,
)

logger = get_logger("app.presentation.api.v1.routes.passport_routes.bulk_actions")


async def _active_roster_resolution_references(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> set[uuid.UUID]:
    """Return submissions whose deletion would corrupt an active roster decision."""

    result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.client_group_id == group_id,
            PassportRosterResolutionModel.agency_id == agency_id,
            PassportRosterResolutionModel.status == "active",
        )
    )
    referenced_ids: set[uuid.UUID] = set()
    for resolution in result.scalars().all():
        referenced_ids.add(resolution.submission_id)
        for value in resolution.excluded_submission_ids or []:
            try:
                referenced_ids.add(uuid.UUID(str(value)))
            except (TypeError, ValueError, AttributeError):
                logger.warning(
                    "passport_roster_resolution_invalid_excluded_submission",
                    resolution_id=str(resolution.id),
                    value_type=type(value).__name__,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "An active replacement record failed its integrity "
                        "check. Restore it before deleting passport uploads."
                    ),
                )
    return referenced_ids


_active_roster_resolution_references.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.bulk_actions"
)
