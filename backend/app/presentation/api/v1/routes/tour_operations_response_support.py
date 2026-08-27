"""Bounded response assembly for tour-operation coordinator and group views."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    PassportSubmissionModel,
    UserModel,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    SUBMITTED_PASSENGER_STATUSES,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AssignedPassengerResponse,
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
        .where(
            CoordinatorGroupAssignmentModel.coordinator_user_id.in_(coordinator_ids),
            CoordinatorGroupAssignmentModel.active.is_(True),
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
        .where(
            CoordinatorGroupAssignmentModel.coordinator_user_id.in_(coordinator_ids),
            CoordinatorGroupAssignmentModel.active.is_(True),
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
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
        .where(
            CoordinatorGroupAssignmentModel.group_id.in_(group_ids),
            CoordinatorGroupAssignmentModel.active.is_(True),
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


async def group_passenger_responses(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> list[AssignedPassengerResponse]:
    assignment_subquery = (
        select(
            CoordinatorAssignmentModel.passenger_id.label("passenger_id"),
            CoordinatorAssignmentModel.coordinator_user_id.label("coordinator_id"),
        )
        .where(
            CoordinatorAssignmentModel.agency_id == agency_id,
            CoordinatorAssignmentModel.group_id == group_id,
            CoordinatorAssignmentModel.active.is_(True),
        )
        .subquery()
    )
    result = await session.execute(
        select(
            PassportSubmissionModel,
            UserModel.id.label("coordinator_id"),
            UserModel.full_name.label("coordinator_name"),
        )
        .outerjoin(
            assignment_subquery,
            assignment_subquery.c.passenger_id == PassportSubmissionModel.id,
        )
        .outerjoin(UserModel, UserModel.id == assignment_subquery.c.coordinator_id)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    rows = result.all()
    sizes = family_sizes([row[0] for row in rows])
    return [
        AssignedPassengerResponse(
            id=passenger.id,
            client_name=passenger.client_name,
            client_email=passenger.client_email,
            client_phone=passenger.client_phone,
            departure_city=passenger.departure_city,
            submission_mode=passenger.submission_mode,
            family_group_id=passenger.family_group_id,
            family_group_label=family_group_label(passenger, sizes),
            family_member_index=passenger.family_member_index,
            family_relation=passenger.family_relation,
            family_gender=passenger.family_gender,
            family_size=family_size(passenger, sizes),
            family_head_name=passenger.family_head_name,
            status=passenger.status,
            coordinator_id=coordinator_id,
            coordinator_name=coordinator_name,
        )
        for passenger, coordinator_id, coordinator_name in rows
    ]


def family_sizes(passengers: list[PassportSubmissionModel]) -> dict[uuid.UUID, int]:
    sizes: dict[uuid.UUID, int] = defaultdict(int)
    for passenger in passengers:
        if passenger.family_group_id:
            sizes[passenger.family_group_id] += 1
    return dict(sizes)


def family_size(
    passenger: PassportSubmissionModel,
    sizes: dict[uuid.UUID, int],
) -> int:
    if not passenger.family_group_id:
        return 1
    return max(1, sizes.get(passenger.family_group_id, 1))


def family_group_label(
    passenger: PassportSubmissionModel,
    sizes: dict[uuid.UUID, int],
) -> str | None:
    if passenger.submission_mode != "family" or not passenger.family_group_id:
        return None
    passenger_family_size = family_size(passenger, sizes)
    kind = "Couple" if passenger_family_size == 2 else "Family"
    return f"{passenger.family_head_name or passenger.client_name} {kind} ({passenger_family_size})"


__all__ = [
    "coordinator_responses",
    "family_group_label",
    "family_size",
    "family_sizes",
    "group_passenger_responses",
    "group_responses",
]
