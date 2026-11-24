"""Current role-scoped notification eligibility queries."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_notification_authority import authoritative_passenger_ids
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCGroupAccessModel,
    MobileNotificationModel,
    MobilePassengerIdentityModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
)
from app.infrastructure.repositories.coordinator_assignment_lifecycle import expired_trip_clause


async def currently_authorized_group_recipients(
    session: AsyncSession,
    *,
    grouped: list[MobileNotificationModel],
    now: datetime,
) -> set[tuple[str, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]]:
    """Read current group and principal grants without changing delivery records."""
    eligible: set[tuple[str, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]] = set()
    passenger_filters = []
    manager_filters = []
    coordinator_filters = []
    for item in grouped:
        principal_id = (
            item.recipient_passenger_identity_id
            if item.recipient_type == "passenger"
            else item.recipient_user_id
        )
        if principal_id is None:
            continue
        condition = and_(
            GCGroupAccessModel.id == item.gc_group_access_id,
            GCGroupAccessModel.agency_id == item.agency_id,
            GCGroupAccessModel.group_id == item.group_id,
        )
        if item.recipient_type == "passenger":
            passenger_filters.append(
                and_(condition, MobilePassengerIdentityModel.id == principal_id)
            )
        elif item.recipient_type == "client_manager":
            manager_filters.append(and_(condition, UserModel.id == principal_id))
        elif item.recipient_type == "coordinator":
            coordinator_filters.append(and_(condition, UserModel.id == principal_id))

    access_conditions = (
        ClientGroupModel.status.in_(("active", "closed")),
        ClientGroupModel.deleted_at.is_(None),
        GCGroupAccessModel.is_enabled.is_(True),
        GCGroupAccessModel.revoked_at.is_(None),
        or_(
            GCGroupAccessModel.access_starts_at.is_(None),
            GCGroupAccessModel.access_starts_at <= now,
        ),
        or_(
            GCGroupAccessModel.access_expires_at.is_(None),
            GCGroupAccessModel.access_expires_at > now,
        ),
    )
    if passenger_filters:
        passenger_rows = (
            await session.execute(
                select(
                    MobilePassengerIdentityModel.agency_id,
                    MobilePassengerIdentityModel.gc_group_access_id,
                    MobilePassengerIdentityModel.group_id,
                    MobilePassengerIdentityModel.id,
                )
                .join(
                    GCGroupAccessModel,
                    GCGroupAccessModel.id == MobilePassengerIdentityModel.gc_group_access_id,
                )
                .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
                .where(
                    *access_conditions,
                    GCGroupAccessModel.passenger_access_enabled.is_(True),
                    MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                    MobilePassengerIdentityModel.revoked_at.is_(None),
                    or_(*passenger_filters),
                )
            )
        ).all()
        allowed_passengers = await authoritative_passenger_ids(
            session, [row[3] for row in passenger_rows]
        )
        eligible.update(
            ("passenger", *row) for row in passenger_rows if row[3] in allowed_passengers
        )
    if manager_filters:
        manager_rows = (
            await session.execute(
                select(
                    GCGroupAccessModel.agency_id,
                    GCGroupAccessModel.id,
                    GCGroupAccessModel.group_id,
                    UserModel.id,
                )
                .join(
                    ClientManagerProfileModel,
                    ClientManagerProfileModel.user_id == UserModel.id,
                )
                .join(
                    ClientManagerGroupAssignmentModel,
                    ClientManagerGroupAssignmentModel.profile_id == ClientManagerProfileModel.id,
                )
                .join(
                    GCGroupAccessModel,
                    GCGroupAccessModel.id == ClientManagerGroupAssignmentModel.gc_group_access_id,
                )
                .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
                .where(
                    *access_conditions,
                    GCGroupAccessModel.client_manager_access_enabled.is_(True),
                    UserModel.role == "client_manager",
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                    ClientManagerProfileModel.status == "active",
                    ClientManagerProfileModel.deleted_at.is_(None),
                    ClientManagerGroupAssignmentModel.is_active.is_(True),
                    ClientManagerGroupAssignmentModel.revoked_at.is_(None),
                    or_(*manager_filters),
                )
            )
        ).all()
        eligible.update(("client_manager", *row) for row in manager_rows)
    if coordinator_filters:
        coordinator_rows = (
            await session.execute(
                select(
                    GCGroupAccessModel.agency_id,
                    GCGroupAccessModel.id,
                    GCGroupAccessModel.group_id,
                    UserModel.id,
                )
                .join(
                    CoordinatorGroupAssignmentModel,
                    CoordinatorGroupAssignmentModel.coordinator_user_id == UserModel.id,
                )
                .join(
                    GCGroupAccessModel,
                    and_(
                        GCGroupAccessModel.agency_id == CoordinatorGroupAssignmentModel.agency_id,
                        GCGroupAccessModel.group_id == CoordinatorGroupAssignmentModel.group_id,
                    ),
                )
                .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
                .where(
                    *access_conditions,
                    GCGroupAccessModel.coordinator_access_enabled.is_(True),
                    UserModel.role == "agency_coordinator",
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                    CoordinatorGroupAssignmentModel.active.is_(True),
                    ~expired_trip_clause(now),
                    or_(*coordinator_filters),
                )
            )
        ).all()
        eligible.update(("coordinator", *row) for row in coordinator_rows)
    return eligible
