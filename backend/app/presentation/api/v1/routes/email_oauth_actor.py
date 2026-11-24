"""Live account/organization eligibility before an OAuth provider exchange."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import AgencyModel, UserModel


async def _oauth_actor_is_authorized(
    session: AsyncSession, *, user_id: uuid.UUID, agency_id: uuid.UUID
) -> bool:
    """Preserve the initial eligibility query; final locked binding stays in each callback."""

    actor_is_still_authorized = await session.scalar(
        select(UserModel.id)
        .outerjoin(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .where(
            UserModel.id == user_id,
            UserModel.is_active.is_(True),
            or_(
                UserModel.role == UserRole.SUPER_ADMIN.value,
                (UserModel.agency_id == agency_id)
                & UserModel.role.in_(
                    {
                        UserRole.AGENCY_ADMIN.value,
                        UserRole.AGENCY_MANAGER.value,
                        UserRole.AGENCY_STAFF.value,
                    }
                )
                & AgencyModel.is_active.is_(True),
            ),
        )
    )
    return actor_is_still_authorized is not None
