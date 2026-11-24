"""Hotel rooming: workspace."""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    ClientGroupModel,
    RoomingAssignmentModel,
    RoomingHotelModel,
    RoomingHotelPassengerModel,
    RoomingPassengerPreferenceModel,
    RoomingRoomModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.observability import metrics
from app.infrastructure.rooming.priority_fields import (
    MAX_ROOMING_PRIORITY_FIELDS,
    ROOMING_GENDER_RULE,
    build_rooming_priority_context,
    is_rooming_roster_field,
)
from app.presentation.api.v1.routes.rooming_allocation_support import (
    priority_field_response as _priority_field_response,
)
from app.presentation.api.v1.routes.rooming_allocation_support import (
    room_number_sort_key as _room_number_sort_key,
)
from app.presentation.api.v1.schemas.rooming_schemas import (
    RoomingHotelResponse,
    RoomingPassengerResponse,
    RoomingPriorityFieldOptionsResponse,
    RoomingRosterFieldValuesResponse,
    RoomingWorkspaceResponse,
)
from app.presentation.dependencies.auth import require_role

from .rooming_access import (
    _allocation_state_is_current,
    _eligible_group_passengers,
    _get_rooming_group,
)
from .rooming_policy import CHECKIN_ROLES, ROOMING_ROLES
from .rooming_presenters import _family_sizes, _passenger_response, _room_response

router = APIRouter()


async def _workspace_response(
    session: AsyncSession, group: ClientGroupModel
) -> RoomingWorkspaceResponse:
    passengers = await _eligible_group_passengers(session, group)
    passengers.sort(key=lambda passenger: (passenger.client_name.casefold(), str(passenger.id)))
    family_sizes = _family_sizes(passengers)
    hotels_result = await session.execute(
        select(RoomingHotelModel)
        .where(RoomingHotelModel.group_id == group.id)
        .order_by(RoomingHotelModel.created_at.asc())
    )
    hotels = list(hotels_result.scalars().all())
    if not hotels:
        return RoomingWorkspaceResponse(
            group_id=group.id,
            group_name=group.name,
            destination=group.destination,
            total_passengers=len(passengers),
            passengers=[
                _passenger_response(passenger, None, family_sizes) for passenger in passengers
            ],
        )

    hotel_ids = [hotel.id for hotel in hotels]
    rooms_result = await session.execute(
        select(RoomingRoomModel).where(RoomingRoomModel.hotel_id.in_(hotel_ids))
    )
    rooms = sorted(
        rooms_result.scalars().all(), key=lambda room: _room_number_sort_key(room.room_number)
    )
    assignments_result = await session.execute(
        select(RoomingAssignmentModel)
        .where(RoomingAssignmentModel.hotel_id.in_(hotel_ids))
        .order_by(RoomingAssignmentModel.position.asc())
    )
    preferences_result = await session.execute(
        select(RoomingPassengerPreferenceModel).where(
            RoomingPassengerPreferenceModel.hotel_id.in_(hotel_ids)
        )
    )
    preference_by_pair = {
        (pref.hotel_id, pref.passenger_id): pref for pref in preferences_result.scalars().all()
    }
    membership_result = await session.execute(
        select(RoomingHotelPassengerModel).where(RoomingHotelPassengerModel.group_id == group.id)
    )
    memberships = list(membership_result.scalars().all())
    membership_by_passenger = {membership.passenger_id: membership for membership in memberships}
    memberships_by_hotel: dict[uuid.UUID, list[RoomingHotelPassengerModel]] = defaultdict(list)
    for membership in memberships:
        memberships_by_hotel[membership.hotel_id].append(membership)
    hotel_name_by_id = {hotel.id: hotel.hotel_name for hotel in hotels}
    passenger_by_id = {passenger.id: passenger for passenger in passengers}
    occupants_by_room: dict[uuid.UUID, list[RoomingPassengerResponse]] = defaultdict(list)
    allocated_by_hotel: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    assignment_count_by_hotel: dict[uuid.UUID, int] = defaultdict(int)
    allocated_passenger_ids: set[uuid.UUID] = set()
    for assignment in assignments_result.scalars().all():
        assignment_count_by_hotel[assignment.hotel_id] += 1
        assigned_passenger = passenger_by_id.get(assignment.passenger_id)
        if assigned_passenger:
            assigned_membership = membership_by_passenger.get(assigned_passenger.id)
            occupants_by_room[assignment.room_id].append(
                _passenger_response(
                    assigned_passenger,
                    preference_by_pair.get((assignment.hotel_id, assigned_passenger.id)),
                    family_sizes,
                    membership=assigned_membership,
                    selected_hotel_name=(
                        hotel_name_by_id.get(assigned_membership.hotel_id)
                        if assigned_membership
                        else None
                    ),
                )
            )
            allocated_by_hotel[assignment.hotel_id].add(assigned_passenger.id)
            allocated_passenger_ids.add(assigned_passenger.id)
    rooms_by_hotel: dict[uuid.UUID, list[RoomingRoomModel]] = defaultdict(list)
    for room in rooms:
        rooms_by_hotel[room.hotel_id].append(room)
    default_hotel_id = hotels[0].id
    unallocated_responses: list[RoomingPassengerResponse] = []
    for passenger in passengers:
        if passenger.id in allocated_passenger_ids:
            continue
        unallocated_membership = membership_by_passenger.get(passenger.id)
        preference_hotel_id = (
            unallocated_membership.hotel_id if unallocated_membership else default_hotel_id
        )
        unallocated_responses.append(
            _passenger_response(
                passenger,
                preference_by_pair.get((preference_hotel_id, passenger.id)),
                family_sizes,
                membership=unallocated_membership,
                selected_hotel_name=(
                    hotel_name_by_id.get(unallocated_membership.hotel_id)
                    if unallocated_membership
                    else None
                ),
            )
        )
    hotel_responses = []
    for hotel in hotels:
        hotel_rooms = rooms_by_hotel[hotel.id]
        hotel_memberships = sorted(
            memberships_by_hotel[hotel.id],
            key=lambda membership: (
                passenger_by_id[membership.passenger_id].client_name.casefold()
                if membership.passenger_id in passenger_by_id
                else "",
                str(membership.passenger_id),
            ),
        )
        selected_ids = {
            membership.passenger_id
            for membership in hotel_memberships
            if membership.passenger_id in passenger_by_id
        }
        allocation_is_current = _allocation_state_is_current(
            hotel=hotel,
            membership_count=len(hotel_memberships),
            selected_ids=selected_ids,
            assigned_ids=allocated_by_hotel[hotel.id],
            assignment_count=assignment_count_by_hotel[hotel.id],
            passenger_by_id=passenger_by_id,
        )
        hotel_responses.append(
            RoomingHotelResponse(
                id=hotel.id,
                hotel_name=hotel.hotel_name,
                city=hotel.city,
                check_in_date=hotel.check_in_date,
                check_out_date=hotel.check_out_date,
                rooms=[_room_response(room, occupants_by_room[room.id]) for room in hotel_rooms],
                unallocated_passengers=list(unallocated_responses),
                allocated_passenger_count=len(allocated_by_hotel[hotel.id]),
                capacity_total=sum(room.capacity for room in hotel_rooms),
                selected_passengers=[
                    _passenger_response(
                        passenger_by_id[membership.passenger_id],
                        preference_by_pair.get((hotel.id, membership.passenger_id)),
                        family_sizes,
                        membership=membership,
                        selected_hotel_name=hotel.hotel_name,
                    )
                    for membership in hotel_memberships
                    if membership.passenger_id in passenger_by_id
                ],
                selected_passenger_count=sum(
                    membership.passenger_id in passenger_by_id for membership in hotel_memberships
                ),
                allocation_priority_fields=[
                    _priority_field_response(field)
                    for field in (hotel.allocation_priority_fields or [])
                ],
                allocation_revision=hotel.allocation_revision,
                allocation_is_current=allocation_is_current,
            )
        )
    return RoomingWorkspaceResponse(
        group_id=group.id,
        group_name=group.name,
        destination=group.destination,
        total_passengers=len(passengers),
        hotels=hotel_responses,
        passengers=[
            _passenger_response(
                passenger,
                preference_by_pair.get((default_hotel_id, passenger.id)),
                family_sizes,
                membership=membership_by_passenger.get(passenger.id),
                selected_hotel_name=(
                    hotel_name_by_id.get(membership_by_passenger[passenger.id].hotel_id)
                    if passenger.id in membership_by_passenger
                    else None
                ),
            )
            for passenger in passengers
        ],
    )


@router.get(
    "/groups/{group_id}",
    response_model=RoomingWorkspaceResponse,
    summary="Get a group's hotel rooming allocation workspace",
)
async def get_rooming_workspace(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(CHECKIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingWorkspaceResponse:
    group = await _get_rooming_group(session, group_id, current_user)
    return await _workspace_response(session, group)


@router.get(
    "/groups/{group_id}/priority-fields",
    response_model=RoomingPriorityFieldOptionsResponse,
    summary="List selectable fields for deterministic automatic room allocation",
)
async def get_rooming_priority_fields(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingPriorityFieldOptionsResponse:
    group = await _get_rooming_group(session, group_id, current_user)
    passengers = await _eligible_group_passengers(session, group)
    context = await build_rooming_priority_context(
        session,
        group=group,
        passengers=passengers,
        resolve_values=False,
    )
    metrics.observe("rooming.priority_catalog.field_count", len(context.fields))
    return RoomingPriorityFieldOptionsResponse(
        group_id=group.id,
        fields=[_priority_field_response(field) for field in context.fields],
        max_priority_fields=MAX_ROOMING_PRIORITY_FIELDS,
        gender_rule=ROOMING_GENDER_RULE,
    )


@router.get(
    "/groups/{group_id}/roster-field-values",
    response_model=RoomingRosterFieldValuesResponse,
    summary="Resolve one authorized Rooming roster field lazily",
)
async def get_rooming_roster_field_values(
    group_id: uuid.UUID,
    field_key: str = Query(..., min_length=1, max_length=180),
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingRosterFieldValuesResponse:
    group = await _get_rooming_group(session, group_id, current_user)
    passengers = await _eligible_group_passengers(session, group)
    context = await build_rooming_priority_context(
        session,
        group=group,
        passengers=passengers,
        requested_keys=[field_key],
    )
    field = next(
        (item for item in context.fields if item["key"] == field_key),
        None,
    )
    if field is None or not is_rooming_roster_field(field):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This field is unavailable for Rooming roster grouping.",
        )
    metrics.observe(
        "rooming.roster_field.passenger_count",
        len(passengers),
    )
    return RoomingRosterFieldValuesResponse(
        group_id=group.id,
        field=_priority_field_response(field),
        values_by_passenger={
            passenger.id: context.values_by_passenger.get(passenger.id, {}).get(field_key)
            for passenger in passengers
        },
    )
