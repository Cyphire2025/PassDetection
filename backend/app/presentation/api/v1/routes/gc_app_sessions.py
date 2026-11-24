"""GC account and group mobile-session revocation boundaries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobilePassengerIdentityModel,
    MobileRefreshTokenModel,
)
from app.infrastructure.database.models import (
    CoordinatorGroupAssignmentModel,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    MobileAudience,
)


async def _revoke_mobile_sessions(
    session: AsyncSession,
    agency_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str,
) -> None:
    now = datetime.now(tz=UTC)
    session_ids = select(MobileDeviceSessionModel.id).where(
        MobileDeviceSessionModel.agency_id == agency_id,
        MobileDeviceSessionModel.user_id == user_id,
        MobileDeviceSessionModel.status == "active",
    )
    await session.execute(
        update(MobileRefreshTokenModel)
        .where(
            MobileRefreshTokenModel.agency_id == agency_id,
            MobileRefreshTokenModel.session_id.in_(session_ids),
            MobileRefreshTokenModel.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason=reason)
    )
    await session.execute(
        update(MobileDeviceSessionModel)
        .where(
            MobileDeviceSessionModel.agency_id == agency_id,
            MobileDeviceSessionModel.user_id == user_id,
            MobileDeviceSessionModel.status == "active",
        )
        .values(
            status="revoked",
            session_generation=MobileDeviceSessionModel.session_generation + 1,
            revoked_at=now,
            revoke_reason=reason,
            updated_at=now,
        )
    )


async def _revoke_group_mobile_sessions(
    session: AsyncSession,
    access: GCGroupAccessModel,
    *,
    subject_roles: set[MobileAudience],
    reason: str,
) -> None:
    """Fence sessions affected by a group-level role or time-window revocation."""

    role_filters = []
    if "passenger" in subject_roles:
        passenger_identity_ids = select(MobilePassengerIdentityModel.id).where(
            MobilePassengerIdentityModel.agency_id == access.agency_id,
            MobilePassengerIdentityModel.gc_group_access_id == access.id,
            MobilePassengerIdentityModel.group_id == access.group_id,
        )
        role_filters.append(
            and_(
                MobileDeviceSessionModel.subject_role == "passenger",
                MobileDeviceSessionModel.passenger_identity_id.in_(passenger_identity_ids),
            )
        )
    if "client_manager" in subject_roles:
        manager_user_ids = (
            select(ClientManagerProfileModel.user_id)
            .join(
                ClientManagerGroupAssignmentModel,
                ClientManagerGroupAssignmentModel.profile_id == ClientManagerProfileModel.id,
            )
            .where(
                ClientManagerProfileModel.agency_id == access.agency_id,
                ClientManagerGroupAssignmentModel.agency_id == access.agency_id,
                ClientManagerGroupAssignmentModel.gc_group_access_id == access.id,
                ClientManagerGroupAssignmentModel.group_id == access.group_id,
            )
        )
        role_filters.append(
            and_(
                MobileDeviceSessionModel.subject_role == "client_manager",
                MobileDeviceSessionModel.user_id.in_(manager_user_ids),
            )
        )
    if "coordinator" in subject_roles:
        coordinator_user_ids = select(CoordinatorGroupAssignmentModel.coordinator_user_id).where(
            CoordinatorGroupAssignmentModel.agency_id == access.agency_id,
            CoordinatorGroupAssignmentModel.group_id == access.group_id,
        )
        role_filters.append(
            and_(
                MobileDeviceSessionModel.subject_role == "coordinator",
                MobileDeviceSessionModel.user_id.in_(coordinator_user_ids),
            )
        )
    if not role_filters:
        return

    now = datetime.now(tz=UTC)
    affected_session_ids = select(MobileDeviceSessionModel.id).where(
        MobileDeviceSessionModel.agency_id == access.agency_id,
        MobileDeviceSessionModel.status == "active",
        MobileDeviceSessionModel.revoked_at.is_(None),
        or_(
            and_(
                MobileDeviceSessionModel.selected_gc_group_access_id == access.id,
                MobileDeviceSessionModel.subject_role.in_(subject_roles),
            ),
            *role_filters,
        ),
    )
    await session.execute(
        update(MobileRefreshTokenModel)
        .where(
            MobileRefreshTokenModel.agency_id == access.agency_id,
            MobileRefreshTokenModel.session_id.in_(affected_session_ids),
            MobileRefreshTokenModel.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason=reason)
    )
    await session.execute(
        update(MobileDeviceSessionModel)
        .where(MobileDeviceSessionModel.id.in_(affected_session_ids))
        .values(
            status="revoked",
            session_generation=MobileDeviceSessionModel.session_generation + 1,
            revoked_at=now,
            revoke_reason=reason,
            updated_at=now,
        )
    )
