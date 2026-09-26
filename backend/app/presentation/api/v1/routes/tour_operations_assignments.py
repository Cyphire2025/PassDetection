"""Assignments for tour operations; preserve tenant, lock and transaction boundaries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.coordinator_assignment_lifecycle import current_trip_clause
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    SUBMITTED_PASSENGER_STATUSES,
)
from app.presentation.api.v1.routes.tour_operations_response_support import (
    group_responses as _group_responses,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AssignedPassengerDetailResponse,
    AssignedPassengerResponse,
    AssignGroupCoordinatorsRequest,
    AssignGroupPassengersRequest,
    TourOperationsGroupResponse,
)
from app.presentation.dependencies.auth import require_role

from .tour_operations_access import (
    COORDINATOR_MANAGEMENT_ROLES,
    TOUR_OPERATION_GROUP_STATUSES,
    _agency_scope,
    _ensure_group_assigned_to_coordinator,
    _get_manageable_group,
    _require_agency,
    _require_assignable_trip,
)
from .tour_operations_passenger_views import (
    _assigned_passenger_response,
    _family_sizes,
    _group_passenger_responses,
)

router = APIRouter()


@router.get(
    "/groups",
    response_model=list[TourOperationsGroupResponse],
    status_code=status.HTTP_200_OK,
    summary="List tour operation groups with coordinator coverage",
)
async def list_tour_operation_groups(
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    assignment_eligible_only: bool = False,
) -> list[TourOperationsGroupResponse]:
    agency_id = _agency_scope(current_user)
    filters: list[ColumnElement[bool]] = [
        ClientGroupModel.status.in_(TOUR_OPERATION_GROUP_STATUSES),
    ]
    if agency_id is not None:
        filters.append(ClientGroupModel.agency_id == agency_id)
    if assignment_eligible_only:
        filters.append(current_trip_clause())

    stmt = AuthorizationPolicy.apply_group_visibility_scope(
        select(ClientGroupModel).where(*filters), current_user
    )
    groups_result = await session.execute(stmt.order_by(ClientGroupModel.created_at.desc()))
    return await _group_responses(session, list(groups_result.scalars().all()))


@router.put(
    "/groups/{group_id}/coordinators",
    response_model=TourOperationsGroupResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign multiple coordinators and evenly divide group passengers",
)
async def assign_group_coordinators(
    group_id: uuid.UUID,
    body: AssignGroupCoordinatorsRequest,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> TourOperationsGroupResponse:
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(
        session,
        agency_id,
        group_id,
        current_user,
        lock_for_update=True,
    )
    coordinator_ids = list(dict.fromkeys(body.coordinator_ids))

    if coordinator_ids:
        _require_assignable_trip(group)
        coordinator_result = await session.execute(
            select(UserModel.id).where(
                UserModel.id.in_(coordinator_ids),
                UserModel.agency_id == agency_id,
                UserModel.role == UserRole.AGENCY_COORDINATOR.value,
                UserModel.is_active.is_(True),
            )
        )
        valid_ids = set(coordinator_result.scalars().all())
        if valid_ids != set(coordinator_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more coordinators are not assignable",
            )

    now = datetime.now(tz=UTC)
    await session.execute(
        update(CoordinatorGroupAssignmentModel)
        .where(
            CoordinatorGroupAssignmentModel.agency_id == agency_id,
            CoordinatorGroupAssignmentModel.group_id == group_id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
        .values(active=False, unassigned_at=now)
    )

    if coordinator_ids:
        for coordinator_id in coordinator_ids:
            session.add(
                CoordinatorGroupAssignmentModel(
                    agency_id=agency_id,
                    group_id=group_id,
                    coordinator_user_id=coordinator_id,
                    assigned_by_user_id=current_user.id,
                    active=True,
                    assigned_at=now,
                )
            )

        await session.execute(
            update(CoordinatorAssignmentModel)
            .where(
                CoordinatorAssignmentModel.agency_id == agency_id,
                CoordinatorAssignmentModel.group_id == group_id,
                CoordinatorAssignmentModel.active.is_(True),
                CoordinatorAssignmentModel.coordinator_user_id.notin_(coordinator_ids),
            )
            .values(active=False, unassigned_at=now)
        )
    else:
        await session.execute(
            update(CoordinatorAssignmentModel)
            .where(
                CoordinatorAssignmentModel.agency_id == agency_id,
                CoordinatorAssignmentModel.group_id == group_id,
                CoordinatorAssignmentModel.active.is_(True),
            )
            .values(active=False, unassigned_at=now)
        )

    await session.flush()
    return (await _group_responses(session, [group]))[0]


@router.get(
    "/groups/{group_id}/passengers",
    response_model=list[AssignedPassengerResponse],
    status_code=status.HTTP_200_OK,
    summary="List submitted passengers in a tour group with coordinator assignment",
)
async def list_group_passengers(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[AssignedPassengerResponse]:
    agency_id = _require_agency(current_user)
    await _get_manageable_group(session, agency_id, group_id, current_user)
    return await _group_passenger_responses(session, agency_id, group_id)


@router.put(
    "/groups/{group_id}/passengers/assign",
    response_model=list[AssignedPassengerResponse],
    status_code=status.HTTP_200_OK,
    summary="Assign selected group passengers to one assigned coordinator",
)
async def assign_group_passengers(
    group_id: uuid.UUID,
    body: AssignGroupPassengersRequest,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[AssignedPassengerResponse]:
    # Compatibility-only endpoint retained for rollback. The dashboard no
    # longer calls it, and attendance authorization ignores these assignments.
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(
        session, agency_id, group_id, current_user, lock_for_update=True
    )
    if body.coordinator_id is not None:
        _require_assignable_trip(group)
    passenger_ids = list(dict.fromkeys(body.passenger_ids))

    passenger_result = await session.execute(
        select(PassportSubmissionModel.id).where(
            PassportSubmissionModel.id.in_(passenger_ids),
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
    )
    valid_passenger_ids = set(passenger_result.scalars().all())
    if valid_passenger_ids != set(passenger_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more passengers are not assignable",
        )

    if body.coordinator_id is not None:
        coordinator_result = await session.execute(
            select(CoordinatorGroupAssignmentModel.id).where(
                CoordinatorGroupAssignmentModel.agency_id == agency_id,
                CoordinatorGroupAssignmentModel.group_id == group_id,
                CoordinatorGroupAssignmentModel.coordinator_user_id == body.coordinator_id,
                CoordinatorGroupAssignmentModel.active.is_(True),
            )
        )
        if not coordinator_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Coordinator is not assigned to this group",
            )

    now = datetime.now(tz=UTC)
    await session.execute(
        update(CoordinatorAssignmentModel)
        .where(
            CoordinatorAssignmentModel.agency_id == agency_id,
            CoordinatorAssignmentModel.group_id == group_id,
            CoordinatorAssignmentModel.passenger_id.in_(passenger_ids),
            CoordinatorAssignmentModel.active.is_(True),
        )
        .values(active=False, unassigned_at=now)
    )

    if body.coordinator_id is not None:
        for passenger_id in passenger_ids:
            session.add(
                CoordinatorAssignmentModel(
                    agency_id=agency_id,
                    group_id=group_id,
                    passenger_id=passenger_id,
                    coordinator_user_id=body.coordinator_id,
                    assigned_by_user_id=current_user.id,
                    active=True,
                    assigned_at=now,
                )
            )

    await session.flush()
    return await _group_passenger_responses(session, agency_id, group_id)


@router.get(
    "/coordinator/groups",
    response_model=list[TourOperationsGroupResponse],
    status_code=status.HTTP_200_OK,
    summary="List groups assigned to the current coordinator",
)
async def list_my_coordinator_groups(
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> list[TourOperationsGroupResponse]:
    agency_id = _require_agency(current_user)
    groups_result = await session.execute(
        select(ClientGroupModel)
        .where(
            AuthorizationPolicy.coordinator_group_visibility_filter(
                current_user.id,
                agency_id=agency_id,
            )
        )
        .order_by(ClientGroupModel.created_at.desc())
    )
    return await _group_responses(session, list(groups_result.scalars().all()))


@router.get(
    "/coordinator/groups/{group_id}/passengers",
    response_model=list[AssignedPassengerResponse],
    status_code=status.HTTP_200_OK,
    summary="List every submitted passenger in a coordinator-assigned group",
)
async def list_my_group_passengers(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> list[AssignedPassengerResponse]:
    agency_id = _require_agency(current_user)
    await _ensure_group_assigned_to_coordinator(session, agency_id, group_id, current_user.id)
    result = await session.execute(
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    passengers = list(result.scalars().all())
    family_sizes = _family_sizes(passengers)
    return [_assigned_passenger_response(passenger, family_sizes) for passenger in passengers]


@router.get(
    "/coordinator/groups/{group_id}/passengers/{passenger_id}",
    response_model=AssignedPassengerDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one submitted passenger from a coordinator-assigned group",
)
async def get_my_group_passenger_detail(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> AssignedPassengerDetailResponse:
    agency_id = _require_agency(current_user)
    await _ensure_group_assigned_to_coordinator(session, agency_id, group_id, current_user.id)
    result = await session.execute(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.id == passenger_id,
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
    )
    passenger = result.scalar_one_or_none()
    if not passenger:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passenger was not found in this group"
        )
    family_sizes = {passenger.family_group_id: 1} if passenger.family_group_id else {}
    return AssignedPassengerDetailResponse(
        **_assigned_passenger_response(passenger, family_sizes).model_dump(exclude={"qr_payload"}),
        qr_payload=None,
        created_at=passenger.created_at,
        updated_at=passenger.updated_at,
        client_reviewed_at=passenger.client_reviewed_at,
        confirmed_at=passenger.confirmed_at,
        passport_fields=passenger.confirmed_fields or passenger.extracted_fields or {},
        overall_confidence=passenger.overall_confidence,
    )
