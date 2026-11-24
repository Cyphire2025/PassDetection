"""Hotel rooming: auto allocation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.rooming.auto_allocator import (
    RoomingAllocationCandidate,
    build_room_plan,
    normalize_priority_value,
    normalize_rooming_gender,
    room_plan_fingerprint,
)
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    RoomingAssignmentModel,
    RoomingHotelPassengerModel,
    RoomingRoomModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.rooming.priority_fields import (
    ROOMING_GENDER_RULE,
    build_rooming_priority_context,
)
from app.presentation.api.v1.routes.rooming_allocation_support import (
    advance_allocation_revisions as _advance_allocation_revisions,
)
from app.presentation.api.v1.routes.rooming_allocation_support import (
    allocation_mutation_response as _allocation_mutation_response,
)
from app.presentation.api.v1.routes.rooming_allocation_support import (
    clear_room_plans as _clear_room_plans,
)
from app.presentation.api.v1.routes.rooming_allocation_support import (
    lock_affected_rooming_hotels as _lock_affected_rooming_hotels,
)
from app.presentation.api.v1.routes.rooming_allocation_support import (
    lock_rooming_scope as _lock_rooming_scope,
)
from app.presentation.api.v1.routes.rooming_allocation_support import (
    require_expected_allocation_revisions as _require_expected_allocation_revisions,
)
from app.presentation.api.v1.schemas.rooming_schemas import (
    AutoAllocateRoomsRequest,
    RoomingAllocationMutationResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

from .rooming_access import (
    _audit,
    _eligible_group_passengers,
    _get_rooming_hotel,
    _stored_room_plan_matches,
)
from .rooming_policy import ROOMING_ROLES

router = APIRouter()


@router.post(
    "/hotels/{hotel_id}/auto-allocate",
    response_model=RoomingAllocationMutationResponse,
    summary="Automatically create gender-safe single and twin rooms",
    dependencies=[Depends(require_cookie_csrf)],
)
async def auto_allocate_hotel_rooms(
    hotel_id: uuid.UUID,
    body: AutoAllocateRoomsRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingAllocationMutationResponse:
    hotel, group = await _get_rooming_hotel(session, hotel_id, current_user)
    hotel, group = await _lock_rooming_scope(session, hotel, group)
    affected_hotels = await _lock_affected_rooming_hotels(
        session,
        group=group,
        hotel_ids={hotel.id},
    )
    _require_expected_allocation_revisions(
        hotels=affected_hotels,
        expected=body.expected_allocation_revisions,
    )
    hotel = affected_hotels[0]
    memberships = list(
        (
            await session.execute(
                select(RoomingHotelPassengerModel)
                .where(RoomingHotelPassengerModel.hotel_id == hotel.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Select at least one passenger for this hotel before auto allocation.",
        )

    all_passengers = await _eligible_group_passengers(
        session,
        group,
        lock_for_allocation=True,
    )
    passenger_by_id = {passenger.id: passenger for passenger in all_passengers}
    missing_passenger_ids = [
        str(membership.passenger_id)
        for membership in memberships
        if membership.passenger_id not in passenger_by_id
    ]
    if missing_passenger_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{len(missing_passenger_ids)} selected passenger(s) are no longer "
                "eligible. Refresh the hotel selection before allocating rooms."
            ),
        )

    context = await build_rooming_priority_context(
        session,
        group=group,
        passengers=all_passengers,
        requested_keys=body.priority_fields,
        lock_inputs=True,
    )
    catalog_by_key = {field["key"]: field for field in context.fields}
    unknown_fields = [key for key in body.priority_fields if key not in catalog_by_key]
    if unknown_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "One or more priority fields are unavailable for this group "
                f"({', '.join(unknown_fields)}). Refresh the priority options and try again."
            ),
        )
    selected_fields = [catalog_by_key[key] for key in body.priority_fields]

    invalid_gender_ids: list[str] = []
    candidates: list[RoomingAllocationCandidate] = []
    for membership in memberships:
        passenger = passenger_by_id[membership.passenger_id]
        passport_fields = passenger.confirmed_fields or passenger.extracted_fields or {}
        gender = normalize_rooming_gender(passport_fields.get("sex"))
        if not gender:
            invalid_gender_ids.append(str(passenger.id))
            continue
        passenger_values = context.values_by_passenger.get(passenger.id, {})
        candidates.append(
            RoomingAllocationCandidate(
                passenger_id=passenger.id,
                gender=gender,
                is_vip=membership.is_vip,
                priority_values=tuple(
                    normalize_priority_value(passenger_values.get(field["key"]))
                    for field in selected_fields
                ),
                stable_order=(
                    passenger.created_at,
                    passenger.family_member_index or 0,
                    passenger.client_name.casefold(),
                ),
            )
        )
    if invalid_gender_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Auto allocation requires Gender to be Male or Female for all "
                f"selected passengers. Correct {len(invalid_gender_ids)} passenger(s) "
                f"first. {ROOMING_GENDER_RULE}"
            ),
        )

    plan = build_room_plan(candidates, priority_count=len(selected_fields))
    fingerprint = room_plan_fingerprint(
        plan,
        selected_fields,
        candidates=candidates,
    )
    if hotel.allocation_fingerprint == fingerprint and await _stored_room_plan_matches(
        session, hotel.id, plan
    ):
        hotel.allocation_priority_fields = selected_fields
        _advance_allocation_revisions(affected_hotels)
        hotel.allocation_updated_at = datetime.now(tz=UTC)
        await session.flush()
        await _audit(
            session,
            current_user,
            request,
            "rooming.rooms_auto_allocated",
            hotel,
            {
                "allocation_revision": hotel.allocation_revision,
                "priority_fields": [field["key"] for field in selected_fields],
                "selected_passenger_count": len(memberships),
                "room_count": len(plan),
                "reused_current_plan": True,
            },
        )
        return await _allocation_mutation_response(
            session,
            group=group,
            changed_hotels=affected_hotels,
            changed_passenger_ids=set(),
        )

    await _clear_room_plans(
        session,
        hotels=affected_hotels,
        block_if_checkins=True,
    )
    rooms: list[RoomingRoomModel] = []
    for index, planned_room in enumerate(plan, start=1):
        room = RoomingRoomModel(
            hotel_id=hotel.id,
            room_number=str(index),
            room_type=planned_room.room_type,
            capacity=1 if planned_room.room_type == "single" else 2,
            allocation_tag=planned_room.allocation_tag,
            is_saved=True,
            sort_order=index - 1,
        )
        session.add(room)
        rooms.append(room)
    await session.flush()
    for room, planned_room in zip(rooms, plan, strict=True):
        session.add_all(
            [
                RoomingAssignmentModel(
                    hotel_id=hotel.id,
                    room_id=room.id,
                    passenger_id=passenger_id,
                    position=position,
                )
                for position, passenger_id in enumerate(
                    planned_room.passenger_ids,
                    start=1,
                )
            ]
        )
    hotel.allocation_priority_fields = selected_fields
    _advance_allocation_revisions(affected_hotels)
    hotel.allocation_fingerprint = fingerprint
    hotel.allocation_updated_at = datetime.now(tz=UTC)
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        "rooming.rooms_auto_allocated",
        hotel,
        {
            "allocation_revision": hotel.allocation_revision,
            "priority_fields": [field["key"] for field in selected_fields],
            "selected_passenger_count": len(memberships),
            "room_count": len(plan),
            "vip_room_count": sum(room.allocation_tag == "vip" for room in plan),
            "unpaired_non_vip_count": sum(
                room.room_type == "twin" and len(room.passenger_ids) == 1 for room in plan
            ),
            "reused_current_plan": False,
        },
    )
    return await _allocation_mutation_response(
        session,
        group=group,
        changed_hotels=affected_hotels,
        changed_passenger_ids=set(),
    )
