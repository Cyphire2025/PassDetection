"""Passenger views for tour operations; preserve tenant, lock and transaction boundaries."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    CoordinatorAssignmentModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    SUBMITTED_PASSENGER_STATUSES,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import AssignedPassengerResponse


async def _group_passenger_responses(
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
            assignment_subquery, assignment_subquery.c.passenger_id == PassportSubmissionModel.id
        )
        .outerjoin(UserModel, UserModel.id == assignment_subquery.c.coordinator_id)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    rows = result.all()
    family_sizes = _family_sizes([row[0] for row in rows])
    return [
        _assigned_passenger_response(
            passenger,
            family_sizes,
            coordinator_id=coordinator_id,
            coordinator_name=coordinator_name,
        )
        for passenger, coordinator_id, coordinator_name in rows
    ]


def _family_sizes(passengers: list[PassportSubmissionModel]) -> dict[uuid.UUID, int]:
    sizes: dict[uuid.UUID, int] = defaultdict(int)
    for passenger in passengers:
        if passenger.family_group_id:
            sizes[passenger.family_group_id] += 1
    return dict(sizes)


def _family_size(passenger: PassportSubmissionModel, family_sizes: dict[uuid.UUID, int]) -> int:
    if not passenger.family_group_id:
        return 1
    return max(1, family_sizes.get(passenger.family_group_id, 1))


def _family_group_label(
    passenger: PassportSubmissionModel, family_sizes: dict[uuid.UUID, int]
) -> str | None:
    if passenger.submission_mode != "family" or not passenger.family_group_id:
        return None
    family_size = _family_size(passenger, family_sizes)
    kind = "Couple" if family_size == 2 else "Family"
    return f"{passenger.family_head_name or passenger.client_name} {kind} ({family_size})"


def _assigned_passenger_response(
    passenger: PassportSubmissionModel,
    family_sizes: dict[uuid.UUID, int],
    *,
    coordinator_id: uuid.UUID | None = None,
    coordinator_name: str | None = None,
) -> AssignedPassengerResponse:
    """One explicit field projection for office and coordinator passenger lists."""
    return AssignedPassengerResponse(
        id=passenger.id,
        client_name=passenger.client_name,
        client_email=passenger.client_email,
        client_phone=passenger.client_phone,
        departure_city=passenger.departure_city,
        submission_mode=passenger.submission_mode,
        family_group_id=passenger.family_group_id,
        family_group_label=_family_group_label(passenger, family_sizes),
        family_member_index=passenger.family_member_index,
        family_relation=passenger.family_relation,
        family_gender=passenger.family_gender,
        family_size=_family_size(passenger, family_sizes),
        family_head_name=passenger.family_head_name,
        status=passenger.status,
        coordinator_id=coordinator_id,
        coordinator_name=coordinator_name,
    )
