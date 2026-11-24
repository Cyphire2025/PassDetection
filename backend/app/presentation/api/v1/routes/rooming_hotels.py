"""Hotel rooming: hotels."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.rooming.create_hotel import create_hotel
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.rooming_schemas import (
    CreateRoomBatchRequest,
    CreateRoomingHotelRequest,
    RoomingHotelResponse,
    RoomingRoomResponse,
    RoomingWorkspaceResponse,
    UpdatePassengerAllocationRequest,
    UpdateRoomingHotelRequest,
    UpdateRoomOrderRequest,
    UpdateRoomRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

from .rooming_access import _audit, _get_rooming_group, _get_rooming_hotel
from .rooming_policy import ROOMING_ROLES
from .rooming_workspace import _workspace_response

router = APIRouter()


@router.post(
    "/groups/{group_id}/hotels",
    response_model=RoomingHotelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a hotel stay to a group rooming list",
    dependencies=[Depends(require_cookie_csrf)],
)
async def create_rooming_hotel(
    group_id: uuid.UUID,
    body: CreateRoomingHotelRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingHotelResponse:
    group = await _get_rooming_group(session, group_id, current_user)
    hotel = await create_hotel(
        session, agency_id=group.agency_id, group_id=group.id, actor_id=current_user.id, body=body
    )
    await _audit(
        session, current_user, request, "rooming.hotel_created", hotel, {"group_id": str(group.id)}
    )
    return RoomingHotelResponse(
        id=hotel.id,
        hotel_name=hotel.hotel_name,
        city=hotel.city,
        check_in_date=hotel.check_in_date,
        check_out_date=hotel.check_out_date,
        unallocated_passengers=[],
    )


@router.patch(
    "/hotels/{hotel_id}",
    response_model=RoomingHotelResponse,
    summary="Update hotel stay details",
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_rooming_hotel(
    hotel_id: uuid.UUID,
    body: UpdateRoomingHotelRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingHotelResponse:
    hotel, group = await _get_rooming_hotel(session, hotel_id, current_user)
    if body.room_count is not None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Manual room counts have been retired. Select hotel passengers "
                "and run auto room allocation."
            ),
        )
    hotel.hotel_name = body.hotel_name.strip()
    hotel.city = body.city.strip() if body.city else None
    hotel.check_in_date = body.check_in_date
    hotel.check_out_date = body.check_out_date

    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        "rooming.hotel_updated",
        hotel,
        {"room_count": body.room_count},
    )
    workspace = await _workspace_response(session, group)
    return next(item for item in workspace.hotels if item.id == hotel.id)


@router.post(
    "/hotels/{hotel_id}/rooms/generate",
    response_model=list[RoomingRoomResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Generate sequential single, twin, or triple rooms",
    include_in_schema=False,
    dependencies=[Depends(require_cookie_csrf)],
)
async def generate_rooms(
    hotel_id: uuid.UUID,
    body: CreateRoomBatchRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[RoomingRoomResponse]:
    del hotel_id, body, request, current_user, session
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Manual room generation has been retired. Select hotel passengers "
            "and run auto room allocation."
        ),
    )


@router.patch(
    "/rooms/{room_id}",
    response_model=RoomingRoomResponse,
    summary="Update a room's number, type, tag, or notes",
    include_in_schema=False,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_room(
    room_id: uuid.UUID,
    body: UpdateRoomRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingRoomResponse:
    del room_id, body, request, current_user, session
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Manual room editing has been retired. Change hotel passenger "
            "selection or priorities and run auto room allocation again."
        ),
    )


@router.put(
    "/hotels/{hotel_id}/rooms/order",
    response_model=list[RoomingRoomResponse],
    summary="Persist the display order of a hotel's rooms",
    include_in_schema=False,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_room_order(
    hotel_id: uuid.UUID,
    body: UpdateRoomOrderRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[RoomingRoomResponse]:
    del hotel_id, body, request, current_user, session
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Manual room ordering has been retired. Auto room allocation "
            "provides deterministic room order."
        ),
    )


@router.delete(
    "/rooms/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a room and any assignments stored for it",
    include_in_schema=False,
    dependencies=[Depends(require_cookie_csrf)],
)
async def delete_room(
    room_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    del room_id, request, current_user, session
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Manual room deletion has been retired. Change the hotel passenger "
            "selection and run auto room allocation again."
        ),
    )


@router.put(
    "/hotels/{hotel_id}/passengers/{passenger_id}/allocation",
    response_model=RoomingWorkspaceResponse,
    summary="Allocate, move, or unallocate a passenger and save hotel-specific preferences",
    include_in_schema=False,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_passenger_allocation(
    hotel_id: uuid.UUID,
    passenger_id: uuid.UUID,
    body: UpdatePassengerAllocationRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingWorkspaceResponse:
    del hotel_id, passenger_id, body, request, current_user, session
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Manual passenger-to-room allocation has been retired. Select "
            "hotel passengers and run auto room allocation."
        ),
    )
