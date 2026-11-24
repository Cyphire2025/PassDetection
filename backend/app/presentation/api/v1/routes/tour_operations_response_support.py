"""Bounded response assembly for tour-operation coordinator and group views."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories.coordinator_assignment_lifecycle import expired_trip_clause
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    SUBMITTED_PASSENGER_STATUSES,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    CoordinatorResponse,
    GroupCoordinatorAssignmentResponse,
    TourOperationsGroupResponse,
)


async def coordinator_responses(
    session: AsyncSession,
    coordinators: list[UserModel],
) -> list[CoordinatorResponse]:
    if not coordinators:
        return []
    coordinator_ids = [coordinator.id for coordinator in coordinators]
    group_counts_result = await session.execute(
        select(
            CoordinatorGroupAssignmentModel.coordinator_user_id,
            func.count(func.distinct(CoordinatorGroupAssignmentModel.group_id)).label(
                "group_count"
            ),
        )
        .join(ClientGroupModel, ClientGroupModel.id == CoordinatorGroupAssignmentModel.group_id)
        .where(
            CoordinatorGroupAssignmentModel.coordinator_user_id.in_(coordinator_ids),
            CoordinatorGroupAssignmentModel.active.is_(True),
            ~expired_trip_clause(),
        )
        .group_by(CoordinatorGroupAssignmentModel.coordinator_user_id)
    )
    group_counts = {
        row.coordinator_user_id: int(row.group_count) for row in group_counts_result.all()
    }

    passenger_counts_result = await session.execute(
        select(
            CoordinatorGroupAssignmentModel.coordinator_user_id,
            func.count(PassportSubmissionModel.id).label("passenger_count"),
        )
        .join(
            PassportSubmissionModel,
            PassportSubmissionModel.group_id == CoordinatorGroupAssignmentModel.group_id,
        )
        .join(ClientGroupModel, ClientGroupModel.id == CoordinatorGroupAssignmentModel.group_id)
        .where(
            CoordinatorGroupAssignmentModel.coordinator_user_id.in_(coordinator_ids),
            CoordinatorGroupAssignmentModel.active.is_(True),
            ~expired_trip_clause(),
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
        .group_by(CoordinatorGroupAssignmentModel.coordinator_user_id)
    )
    passenger_counts = {
        row.coordinator_user_id: int(row.passenger_count) for row in passenger_counts_result.all()
    }
    return [
        CoordinatorResponse(
            id=coordinator.id,
            full_name=coordinator.full_name,
            email=coordinator.email,
            agency_id=coordinator.agency_id,
            is_active=coordinator.is_active,
            created_at=coordinator.created_at,
            last_login_at=coordinator.last_login_at,
            assigned_groups_count=group_counts.get(coordinator.id, 0),
            assigned_passengers_count=passenger_counts.get(coordinator.id, 0),
        )
        for coordinator in coordinators
        if coordinator.agency_id is not None
    ]


async def group_responses(
    session: AsyncSession,
    groups: list[ClientGroupModel],
) -> list[TourOperationsGroupResponse]:
    if not groups:
        return []
    group_ids = [group.id for group in groups]

    passenger_counts_result = await session.execute(
        select(PassportSubmissionModel.group_id, func.count(PassportSubmissionModel.id))
        .where(
            PassportSubmissionModel.group_id.in_(group_ids),
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
        .group_by(PassportSubmissionModel.group_id)
    )
    passenger_counts = {group_id: int(count) for group_id, count in passenger_counts_result.all()}

    group_coordinators_result = await session.execute(
        select(
            CoordinatorGroupAssignmentModel.group_id,
            UserModel.id,
            UserModel.full_name,
            UserModel.email,
        )
        .join(
            UserModel,
            UserModel.id == CoordinatorGroupAssignmentModel.coordinator_user_id,
        )
        .join(ClientGroupModel, ClientGroupModel.id == CoordinatorGroupAssignmentModel.group_id)
        .where(
            CoordinatorGroupAssignmentModel.group_id.in_(group_ids),
            CoordinatorGroupAssignmentModel.active.is_(True),
            ~expired_trip_clause(),
        )
        .order_by(UserModel.full_name.asc())
    )

    assignments: dict[uuid.UUID, list[GroupCoordinatorAssignmentResponse]] = defaultdict(list)
    for row in group_coordinators_result.all():
        count = passenger_counts.get(row.group_id, 0)
        assignments[row.group_id].append(
            GroupCoordinatorAssignmentResponse(
                coordinator_id=row.id,
                full_name=row.full_name,
                email=row.email,
                assigned_passengers_count=count,
            )
        )

    return [
        TourOperationsGroupResponse(
            id=group.id,
            name=group.name,
            status=group.status,
            destination=group.destination,
            travel_date=group.travel_date.isoformat() if group.travel_date else None,
            return_date=group.return_date.isoformat() if group.return_date else None,
            timezone=group.timezone,
            departure_cities=list(group.departure_cities or []),
            base_city_enabled=group.base_city_enabled,
            nearest_international_airport_enabled=(group.nearest_international_airport_enabled),
            staff_code_enabled=group.staff_code_enabled,
            agent_employee_code_enabled=group.agent_employee_code_enabled,
            meal_preference_enabled=group.meal_preference_enabled,
            require_selfie=group.require_selfie,
            passenger_count=passenger_counts.get(group.id, 0),
            assigned_passengers_count=(
                passenger_counts.get(group.id, 0) if assignments[group.id] else 0
            ),
            unassigned_passengers_count=(
                0 if assignments[group.id] else passenger_counts.get(group.id, 0)
            ),
            coordinators=assignments[group.id],
        )
        for group in groups
    ]


__all__ = ["coordinator_responses", "group_responses"]
