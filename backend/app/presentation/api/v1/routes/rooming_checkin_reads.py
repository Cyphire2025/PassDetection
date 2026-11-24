"""Hotel rooming: checkin reads."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingCheckinModel,
    RoomingHotelModel,
    RoomingPassengerPreferenceModel,
    RoomingRoomModel,
)
from app.infrastructure.observability import metrics
from app.presentation.api.v1.schemas.rooming_schemas import (
    HotelCheckinDashboardResponse,
    HotelCheckinPassengerResponse,
)

from .rooming_presenters import _checkin_item_response, _family_sizes


async def _checkin_dashboard(
    session: AsyncSession, hotel: RoomingHotelModel, group: ClientGroupModel
) -> HotelCheckinDashboardResponse:
    assignments = list(
        (
            await session.execute(
                select(RoomingAssignmentModel)
                .where(RoomingAssignmentModel.hotel_id == hotel.id)
                .order_by(RoomingAssignmentModel.position)
            )
        )
        .scalars()
        .all()
    )
    rooms = {
        room.id: room
        for room in (
            await session.execute(
                select(RoomingRoomModel).where(RoomingRoomModel.hotel_id == hotel.id)
            )
        )
        .scalars()
        .all()
    }
    passenger_ids = [assignment.passenger_id for assignment in assignments]
    passengers = (
        {
            passenger.id: passenger
            for passenger in (
                await session.execute(
                    select(PassportSubmissionModel).where(
                        PassportSubmissionModel.id.in_(passenger_ids),
                        PassportSubmissionModel.group_id == group.id,
                        PassportSubmissionModel.agency_id == group.agency_id,
                    )
                )
            )
            .scalars()
            .all()
        }
        if passenger_ids
        else {}
    )
    checkins = {
        checkin.passenger_id: checkin
        for checkin in (
            await session.execute(
                select(RoomingCheckinModel).where(RoomingCheckinModel.hotel_id == hotel.id)
            )
        )
        .scalars()
        .all()
    }
    preferences = {
        preference.passenger_id: preference
        for preference in (
            await session.execute(
                select(RoomingPassengerPreferenceModel).where(
                    RoomingPassengerPreferenceModel.hotel_id == hotel.id
                )
            )
        )
        .scalars()
        .all()
    }
    assignments_by_room: dict[uuid.UUID, list[RoomingAssignmentModel]] = defaultdict(list)
    for assignment in assignments:
        assignments_by_room[assignment.room_id].append(assignment)
    family_sizes = _family_sizes(passengers.values())
    items: list[HotelCheckinPassengerResponse] = []
    for assignment in assignments:
        passenger = passengers.get(assignment.passenger_id)
        room = rooms.get(assignment.room_id)
        if passenger is None or room is None:
            continue
        occupant_assignments = assignments_by_room[room.id]
        occupants = [
            occupants_passenger
            for occupant_assignment in occupant_assignments
            if (occupants_passenger := passengers.get(occupant_assignment.passenger_id)) is not None
        ]
        items.append(
            _checkin_item_response(
                room=room,
                passenger=passenger,
                checkin=checkins.get(passenger.id),
                preference=preferences.get(passenger.id),
                occupants=occupants,
                family_sizes=family_sizes,
            )
        )
    occupant_count_by_room = {
        room_id: len(room_assignments) for room_id, room_assignments in assignments_by_room.items()
    }
    missing_rooms = sum(
        0 < occupant_count_by_room.get(room.id, 0) < room.capacity for room in rooms.values()
    )
    metrics.observe("rooming.checkin.dashboard.passenger_count", len(items))
    return HotelCheckinDashboardResponse(
        hotel_id=hotel.id,
        hotel_name=hotel.hotel_name,
        group_id=group.id,
        group_name=group.name,
        total_allocated_passengers=len(items),
        checked_in_count=sum(item.checked_in for item in items),
        keys_issued_count=sum(item.key_issued for item in items),
        welcome_letters_issued_count=sum(item.welcome_letter_issued for item in items),
        rooms_complete=sum(
            occupant_count_by_room.get(room.id, 0) >= room.capacity for room in rooms.values()
        ),
        rooms_with_missing_occupants=missing_rooms,
        passengers=items,
    )


async def _checkin_item(
    session: AsyncSession,
    hotel: RoomingHotelModel,
    assignment: RoomingAssignmentModel,
    passenger: PassportSubmissionModel,
    checkin: RoomingCheckinModel | None,
    family_sizes: dict[uuid.UUID, int] | None = None,
) -> HotelCheckinPassengerResponse:
    room = (
        await session.execute(
            select(RoomingRoomModel).where(
                RoomingRoomModel.id == assignment.room_id,
                RoomingRoomModel.hotel_id == hotel.id,
            )
        )
    ).scalar_one()
    occupants = [
        occupant
        for _, occupant in (
            await session.execute(
                select(RoomingAssignmentModel, PassportSubmissionModel)
                .join(
                    PassportSubmissionModel,
                    PassportSubmissionModel.id == RoomingAssignmentModel.passenger_id,
                )
                .where(
                    RoomingAssignmentModel.room_id == room.id,
                    PassportSubmissionModel.group_id == hotel.group_id,
                    PassportSubmissionModel.agency_id == hotel.agency_id,
                )
            )
        ).all()
    ]
    preference = (
        await session.execute(
            select(RoomingPassengerPreferenceModel).where(
                RoomingPassengerPreferenceModel.hotel_id == hotel.id,
                RoomingPassengerPreferenceModel.passenger_id == passenger.id,
            )
        )
    ).scalar_one_or_none()
    return _checkin_item_response(
        room=room,
        passenger=passenger,
        checkin=checkin,
        preference=preference,
        occupants=occupants,
        family_sizes=family_sizes,
    )
