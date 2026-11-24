"""Hotel rooming: selection."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import RoomingHotelPassengerModel
from app.infrastructure.database.session import get_db_session
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
    current_allocation_revisions as _current_allocation_revisions,
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
from app.presentation.api.v1.routes.rooming_allocation_support import (
    unchanged_allocation_mutation_response as _unchanged_allocation_mutation_response,
)
from app.presentation.api.v1.schemas.rooming_schemas import (
    RoomingAllocationMutationResponse,
    UpdateHotelPassengerSelectionRequest,
    UpdateHotelVipRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

from .rooming_access import _audit, _eligible_group_passengers, _get_rooming_hotel
from .rooming_policy import ROOMING_ROLES

router = APIRouter()


@router.put(
    "/hotels/{hotel_id}/passenger-selection",
    response_model=RoomingAllocationMutationResponse,
    summary="Select, move, or remove hotel passengers in one transaction",
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_hotel_passenger_selection(
    hotel_id: uuid.UUID,
    body: UpdateHotelPassengerSelectionRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingAllocationMutationResponse:
    hotel, group = await _get_rooming_hotel(session, hotel_id, current_user)
    hotel, group = await _lock_rooming_scope(session, hotel, group)
    requested_ids = set(body.passenger_ids)
    if requested_ids:
        eligible = await _eligible_group_passengers(
            session,
            group,
            passenger_ids=requested_ids,
            lock_for_allocation=True,
        )
        if {passenger.id for passenger in eligible} != requested_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Every selected passenger must be an eligible member of this group.",
            )

    memberships = list(
        (
            await session.execute(
                select(RoomingHotelPassengerModel)
                .where(RoomingHotelPassengerModel.group_id == group.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    membership_by_passenger = {membership.passenger_id: membership for membership in memberships}
    current_ids = {
        membership.passenger_id for membership in memberships if membership.hotel_id == hotel.id
    }
    if body.mode == "replace":
        target_ids = requested_ids
    elif body.mode == "add":
        target_ids = current_ids | requested_ids
    else:
        target_ids = current_ids - requested_ids

    added_ids = target_ids - current_ids
    removed_ids = current_ids - target_ids
    moved_ids = {
        passenger_id
        for passenger_id in added_ids
        if (
            passenger_id in membership_by_passenger
            and membership_by_passenger[passenger_id].hotel_id != hotel.id
        )
    }
    changed_ids = added_ids | removed_ids
    affected_hotel_ids = {hotel.id}
    affected_hotel_ids.update(
        membership_by_passenger[passenger_id].hotel_id for passenger_id in moved_ids
    )
    affected_hotels = await _lock_affected_rooming_hotels(
        session,
        group=group,
        hotel_ids=affected_hotel_ids,
    )
    _require_expected_allocation_revisions(
        hotels=affected_hotels,
        expected=body.expected_allocation_revisions,
    )
    hotel = next(item for item in affected_hotels if item.id == hotel.id)
    if changed_ids:
        await _clear_room_plans(
            session,
            hotels=affected_hotels,
            block_if_checkins=True,
        )

    for passenger_id in removed_ids:
        membership = membership_by_passenger[passenger_id]
        await session.delete(membership)
    for passenger_id in added_ids:
        existing_membership = membership_by_passenger.get(passenger_id)
        if existing_membership is None:
            session.add(
                RoomingHotelPassengerModel(
                    agency_id=group.agency_id,
                    group_id=group.id,
                    hotel_id=hotel.id,
                    passenger_id=passenger_id,
                )
            )
        else:
            existing_membership.agency_id = group.agency_id
            existing_membership.group_id = group.id
            existing_membership.hotel_id = hotel.id
    if changed_ids:
        _advance_allocation_revisions(affected_hotels)
    await session.flush()
    if changed_ids:
        await _audit(
            session,
            current_user,
            request,
            "rooming.hotel_passengers_selected",
            hotel,
            {
                "mode": body.mode,
                "added_count": len(added_ids),
                "removed_count": len(removed_ids),
                "moved_count": len(moved_ids),
                "selected_count": len(target_ids),
                "requested_passenger_count": len(body.passenger_ids),
                "allocation_revisions": {
                    str(identifier): revision
                    for identifier, revision in _current_allocation_revisions(
                        affected_hotels
                    ).items()
                },
            },
        )
        return await _allocation_mutation_response(
            session,
            group=group,
            changed_hotels=affected_hotels,
            changed_passenger_ids=changed_ids,
        )
    return _unchanged_allocation_mutation_response(
        group=group,
        hotels=affected_hotels,
    )


@router.put(
    "/hotels/{hotel_id}/vip",
    response_model=RoomingAllocationMutationResponse,
    summary="Mark selected hotel passengers as VIP or non-VIP",
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_hotel_vip_status(
    hotel_id: uuid.UUID,
    body: UpdateHotelVipRequest,
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
    requested_ids = set(body.passenger_ids)
    memberships = list(
        (
            await session.execute(
                select(RoomingHotelPassengerModel)
                .where(
                    RoomingHotelPassengerModel.hotel_id == hotel.id,
                    RoomingHotelPassengerModel.passenger_id.in_(requested_ids),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if {membership.passenger_id for membership in memberships} != requested_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="VIP status can be changed only for passengers selected for this hotel.",
        )
    changed = [membership for membership in memberships if membership.is_vip is not body.is_vip]
    if changed:
        await _clear_room_plans(
            session,
            hotels=affected_hotels,
            block_if_checkins=True,
        )
        for membership in changed:
            membership.is_vip = body.is_vip
        _advance_allocation_revisions(affected_hotels)
        await session.flush()
        await _audit(
            session,
            current_user,
            request,
            "rooming.hotel_vip_updated",
            hotel,
            {
                "is_vip": body.is_vip,
                "changed_count": len(changed),
                "requested_passenger_count": len(body.passenger_ids),
                "allocation_revisions": {
                    str(identifier): revision
                    for identifier, revision in _current_allocation_revisions(
                        affected_hotels
                    ).items()
                },
            },
        )
        return await _allocation_mutation_response(
            session,
            group=group,
            changed_hotels=affected_hotels,
            changed_passenger_ids={membership.passenger_id for membership in changed},
        )
    return _unchanged_allocation_mutation_response(
        group=group,
        hotels=affected_hotels,
    )
