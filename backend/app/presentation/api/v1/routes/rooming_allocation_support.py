"""Concurrency fencing and bounded projections for rooming allocation commands."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClientGroupModel,
    RoomingAssignmentModel,
    RoomingCheckinModel,
    RoomingHotelModel,
    RoomingHotelPassengerModel,
    RoomingRoomModel,
)
from app.infrastructure.rooming.priority_fields import is_rooming_roster_field
from app.presentation.api.v1.schemas.rooming_schemas import (
    RoomingAllocationMutationResponse,
    RoomingHotelAllocationDeltaResponse,
    RoomingPassengerAllocationDeltaResponse,
    RoomingPriorityFieldResponse,
    RoomingRoomAllocationDeltaResponse,
)


async def lock_rooming_scope(
    session: AsyncSession,
    hotel: RoomingHotelModel,
    group: ClientGroupModel,
) -> tuple[RoomingHotelModel, ClientGroupModel]:
    """Serialize every membership mutation for a group before locking its hotel."""

    locked_group = (
        await session.execute(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == group.id,
                ClientGroupModel.status != "deleted",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    locked_hotel = (
        await session.execute(
            select(RoomingHotelModel)
            .where(RoomingHotelModel.id == hotel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if (
        locked_group is None
        or locked_hotel is None
        or locked_hotel.group_id != locked_group.id
        or locked_hotel.agency_id != locked_group.agency_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The hotel or group changed while this operation was starting.",
        )
    return locked_hotel, locked_group


async def lock_affected_rooming_hotels(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    hotel_ids: set[uuid.UUID],
) -> list[RoomingHotelModel]:
    """Lock the complete revision scope in a deterministic order."""

    hotels = list(
        (
            await session.execute(
                select(RoomingHotelModel)
                .where(
                    RoomingHotelModel.id.in_(hotel_ids),
                    RoomingHotelModel.group_id == group.id,
                    RoomingHotelModel.agency_id == group.agency_id,
                )
                .order_by(RoomingHotelModel.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    if {item.id for item in hotels} != hotel_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more affected hotels changed while the operation was starting.",
        )
    return hotels


def current_allocation_revisions(
    hotels: Iterable[RoomingHotelModel],
) -> dict[uuid.UUID, int]:
    return {
        hotel.id: int(hotel.allocation_revision)
        for hotel in sorted(hotels, key=lambda item: str(item.id))
    }


def require_expected_allocation_revisions(
    *,
    hotels: Iterable[RoomingHotelModel],
    expected: Mapping[uuid.UUID, int],
) -> dict[uuid.UUID, int]:
    """Reject stale or incomplete commands before any allocation state changes."""

    current = current_allocation_revisions(hotels)
    conflicting_ids = [
        hotel_id for hotel_id, revision in current.items() if expected.get(hotel_id) != revision
    ]
    if conflicting_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ROOMING_ALLOCATION_REVISION_CONFLICT",
                "message": (
                    "Rooming changed in another session. The latest allocation "
                    "is being refreshed; review it and try again."
                ),
                "current_revisions": {
                    str(hotel_id): revision for hotel_id, revision in current.items()
                },
                "conflicting_hotel_ids": [str(hotel_id) for hotel_id in conflicting_ids],
            },
        )
    return current


def advance_allocation_revisions(
    hotels: Iterable[RoomingHotelModel],
) -> None:
    """Advance each changed hotel exactly once for the committed command."""

    unique_hotels = {hotel.id: hotel for hotel in hotels}
    for hotel in unique_hotels.values():
        hotel.allocation_revision = int(hotel.allocation_revision) + 1


async def clear_room_plans(
    session: AsyncSession,
    *,
    hotels: Iterable[RoomingHotelModel],
    block_if_checkins: bool,
) -> None:
    """Invalidate plans for already locked hotels without erasing check-ins."""

    hotels = list(hotels)
    hotel_ids = {hotel.id for hotel in hotels}
    if not hotel_ids:
        return
    if block_if_checkins:
        checkin_count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(RoomingCheckinModel)
                    .where(RoomingCheckinModel.hotel_id.in_(hotel_ids))
                )
            ).scalar_one()
        )
        if checkin_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Room allocation cannot be changed after hotel check-in activity has started."
                ),
            )
    await session.execute(
        delete(RoomingAssignmentModel).where(RoomingAssignmentModel.hotel_id.in_(hotel_ids))
    )
    await session.execute(delete(RoomingRoomModel).where(RoomingRoomModel.hotel_id.in_(hotel_ids)))
    for item in hotels:
        item.allocation_fingerprint = None
        item.allocation_updated_at = None
    await session.flush()


def unchanged_allocation_mutation_response(
    *,
    group: ClientGroupModel,
    hotels: Iterable[RoomingHotelModel],
) -> RoomingAllocationMutationResponse:
    return RoomingAllocationMutationResponse(
        group_id=group.id,
        changed=False,
        current_revisions=current_allocation_revisions(hotels),
    )


async def allocation_mutation_response(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    changed_hotels: Iterable[RoomingHotelModel],
    changed_passenger_ids: set[uuid.UUID],
) -> RoomingAllocationMutationResponse:
    """Project a bounded mutation delta instead of rebuilding the workspace."""

    hotels = sorted(changed_hotels, key=lambda item: str(item.id))
    hotel_ids = {hotel.id for hotel in hotels}
    rooms = sorted(
        (
            (
                await session.execute(
                    select(RoomingRoomModel).where(RoomingRoomModel.hotel_id.in_(hotel_ids))
                )
            )
            .scalars()
            .all()
        ),
        key=lambda room: (
            str(room.hotel_id),
            room.sort_order,
            room_number_sort_key(room.room_number),
        ),
    )
    assignments = list(
        (
            await session.execute(
                select(RoomingAssignmentModel)
                .where(RoomingAssignmentModel.hotel_id.in_(hotel_ids))
                .order_by(
                    RoomingAssignmentModel.hotel_id.asc(),
                    RoomingAssignmentModel.room_id.asc(),
                    RoomingAssignmentModel.position.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    memberships = list(
        (
            await session.execute(
                select(RoomingHotelPassengerModel).where(
                    RoomingHotelPassengerModel.group_id == group.id,
                    RoomingHotelPassengerModel.hotel_id.in_(hotel_ids),
                )
            )
        )
        .scalars()
        .all()
    )

    rooms_by_hotel: dict[uuid.UUID, list[RoomingRoomModel]] = defaultdict(list)
    for room in rooms:
        rooms_by_hotel[room.hotel_id].append(room)
    occupant_ids_by_room: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    assigned_ids_by_hotel: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    assignment_count_by_hotel: dict[uuid.UUID, int] = defaultdict(int)
    for assignment in assignments:
        occupant_ids_by_room[assignment.room_id].append(assignment.passenger_id)
        assigned_ids_by_hotel[assignment.hotel_id].add(assignment.passenger_id)
        assignment_count_by_hotel[assignment.hotel_id] += 1
    memberships_by_hotel: dict[uuid.UUID, list[RoomingHotelPassengerModel]] = defaultdict(list)
    membership_by_passenger: dict[uuid.UUID, RoomingHotelPassengerModel] = {}
    for membership in memberships:
        memberships_by_hotel[membership.hotel_id].append(membership)
        membership_by_passenger[membership.passenger_id] = membership

    hotel_deltas: list[RoomingHotelAllocationDeltaResponse] = []
    for hotel in hotels:
        hotel_rooms = rooms_by_hotel[hotel.id]
        selected_ids = {membership.passenger_id for membership in memberships_by_hotel[hotel.id]}
        assigned_ids = assigned_ids_by_hotel[hotel.id]
        allocation_is_current = bool(
            selected_ids
            and hotel.allocation_fingerprint
            and hotel.allocation_updated_at
            and selected_ids == assigned_ids
            and assignment_count_by_hotel[hotel.id] == len(selected_ids)
        )
        hotel_deltas.append(
            RoomingHotelAllocationDeltaResponse(
                hotel_id=hotel.id,
                rooms=[
                    RoomingRoomAllocationDeltaResponse(
                        id=room.id,
                        room_number=room.room_number,
                        room_type=room.room_type,
                        capacity=room.capacity,
                        allocation_tag=room.allocation_tag,
                        roommate_notes=room.roommate_notes,
                        is_saved=room.is_saved,
                        sort_order=room.sort_order,
                        occupant_ids=occupant_ids_by_room[room.id],
                    )
                    for room in hotel_rooms
                ],
                allocation_priority_fields=[
                    priority_field_response(field)
                    for field in (hotel.allocation_priority_fields or [])
                ],
                allocation_revision=hotel.allocation_revision,
                allocation_is_current=allocation_is_current,
                allocated_passenger_count=len(assigned_ids),
                capacity_total=sum(room.capacity for room in hotel_rooms),
            )
        )

    passenger_deltas = []
    for passenger_id in sorted(changed_passenger_ids, key=str):
        passenger_membership = membership_by_passenger.get(passenger_id)
        passenger_deltas.append(
            RoomingPassengerAllocationDeltaResponse(
                passenger_id=passenger_id,
                selected_hotel_id=(passenger_membership.hotel_id if passenger_membership else None),
                is_vip=bool(passenger_membership and passenger_membership.is_vip),
            )
        )
    return RoomingAllocationMutationResponse(
        group_id=group.id,
        changed=True,
        current_revisions=current_allocation_revisions(hotels),
        hotels=hotel_deltas,
        passengers=passenger_deltas,
    )


def priority_field_response(field: dict[str, str]) -> RoomingPriorityFieldResponse:
    return RoomingPriorityFieldResponse(
        key=field["key"],
        label=field["label"],
        source=field["source"],
        groupable=is_rooming_roster_field(field),
    )


def room_number_sort_key(room_number: str) -> tuple[int, str]:
    match = re.match(r"^(\d+)(.*)$", room_number.strip())
    if not match:
        return (10**9, room_number.casefold())
    return (int(match.group(1)), match.group(2).casefold())
