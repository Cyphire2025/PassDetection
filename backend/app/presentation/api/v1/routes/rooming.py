"""Hotel rooming lists and room allocation operations."""

from __future__ import annotations

import io
import re
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingCheckinModel,
    RoomingHotelModel,
    RoomingPassengerPreferenceModel,
    RoomingRoomModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.rooming_excel_exporter import RoomingExcelExporter
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.tour_operations_qr_helpers import qr_hash
from app.presentation.api.v1.schemas.rooming_schemas import (
    ROOM_TYPES,
    CreateRoomBatchRequest,
    CreateRoomingHotelRequest,
    HotelCheckinDashboardResponse,
    HotelCheckinPassengerResponse,
    HotelCheckinScanRequest,
    HotelCheckinScanResponse,
    RoomingHotelResponse,
    RoomingPassengerResponse,
    RoomingRoomResponse,
    RoomingWorkspaceResponse,
    UpdateHotelCheckinRequest,
    UpdatePassengerAllocationRequest,
    UpdateRoomingHotelRequest,
    UpdateRoomOrderRequest,
    UpdateRoomRequest,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()
ROOMING_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF]
CHECKIN_ROLES = [*ROOMING_ROLES, UserRole.AGENCY_COORDINATOR]
ROOMING_PASSENGER_STATUSES = ("client_submitted", "confirmed")


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


@router.post(
    "/groups/{group_id}/hotels",
    response_model=RoomingHotelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a hotel stay to a group rooming list",
)
async def create_rooming_hotel(
    group_id: uuid.UUID,
    body: CreateRoomingHotelRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingHotelResponse:
    group = await _get_rooming_group(session, group_id, current_user)
    hotel = RoomingHotelModel(
        agency_id=group.agency_id,
        group_id=group.id,
        hotel_name=body.hotel_name.strip(),
        city=body.city.strip() if body.city else None,
        check_in_date=body.check_in_date,
        check_out_date=body.check_out_date,
        created_by_user_id=current_user.id,
    )
    session.add(hotel)
    await session.flush()
    await _audit(session, current_user, request, "rooming.hotel_created", hotel, {"group_id": str(group.id)})
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
    summary="Update a hotel stay and safely adjust its total rooms",
)
async def update_rooming_hotel(
    hotel_id: uuid.UUID,
    body: UpdateRoomingHotelRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingHotelResponse:
    hotel, _ = await _get_rooming_hotel(session, hotel_id, current_user)
    hotel.hotel_name = body.hotel_name.strip()
    hotel.city = body.city.strip() if body.city else None
    hotel.check_in_date = body.check_in_date
    hotel.check_out_date = body.check_out_date

    rooms_result = await session.execute(select(RoomingRoomModel).where(RoomingRoomModel.hotel_id == hotel.id))
    rooms = sorted(rooms_result.scalars().all(), key=lambda room: (room.sort_order, _room_number_sort_key(room.room_number)))
    if body.room_count is not None:
        difference = body.room_count - len(rooms)
        if difference < 0:
            rooms_to_delete = rooms[difference:]
            occupied_room_ids = set((await session.execute(select(RoomingAssignmentModel.room_id).where(RoomingAssignmentModel.room_id.in_([room.id for room in rooms_to_delete])))).scalars().all())
            if occupied_room_ids:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Move occupants before reducing the total rooms")
            for room in rooms_to_delete:
                await session.delete(room)
            rooms = rooms[:difference]
        elif difference > 0:
            start_number = await _next_room_number(session, hotel.id)
            template = rooms[-1] if rooms else None
            new_rooms = [
                RoomingRoomModel(
                    hotel_id=hotel.id,
                    room_number=str(start_number + offset),
                    room_type=template.room_type if template else "twin",
                    capacity=template.capacity if template else ROOM_TYPES["twin"],
                    allocation_tag=template.allocation_tag if template else "mixed",
                    sort_order=len(rooms) + offset,
                )
                for offset in range(difference)
            ]
            session.add_all(new_rooms)
            rooms.extend(new_rooms)

    await session.flush()
    await _audit(session, current_user, request, "rooming.hotel_updated", hotel, {"room_count": body.room_count})
    return RoomingHotelResponse(
        id=hotel.id, hotel_name=hotel.hotel_name, city=hotel.city,
        check_in_date=hotel.check_in_date, check_out_date=hotel.check_out_date,
        rooms=[_room_response(room, []) for room in rooms],
        capacity_total=sum(room.capacity for room in rooms),
    )


@router.post(
    "/hotels/{hotel_id}/rooms/generate",
    response_model=list[RoomingRoomResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Generate sequential single, twin, or triple rooms",
)
async def generate_rooms(
    hotel_id: uuid.UUID,
    body: CreateRoomBatchRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[RoomingRoomResponse]:
    hotel, _ = await _get_rooming_hotel(session, hotel_id, current_user)
    start_number = body.starting_number or await _next_room_number(session, hotel.id)
    room_numbers = [str(start_number + offset) for offset in range(body.count)]
    existing = await session.execute(
        select(RoomingRoomModel.room_number).where(
            RoomingRoomModel.hotel_id == hotel.id,
            RoomingRoomModel.room_number.in_(room_numbers),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="One or more room numbers already exist")

    existing_room_count = await _room_count(session, hotel.id)
    rooms = [
        RoomingRoomModel(
            hotel_id=hotel.id,
            room_number=room_number,
            room_type=body.room_type,
            capacity=ROOM_TYPES[body.room_type],
            allocation_tag=body.allocation_tag,
            sort_order=existing_room_count + offset,
        )
        for offset, room_number in enumerate(room_numbers)
    ]
    session.add_all(rooms)
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        "rooming.rooms_generated",
        hotel,
        {"room_type": body.room_type, "count": body.count, "starting_number": start_number},
    )
    return [_room_response(room, []) for room in rooms]


@router.patch(
    "/rooms/{room_id}",
    response_model=RoomingRoomResponse,
    summary="Update a room's number, type, tag, or notes",
)
async def update_room(
    room_id: uuid.UUID,
    body: UpdateRoomRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingRoomResponse:
    room, hotel, _ = await _get_room(session, room_id, current_user)
    occupancy = await _room_occupancy(session, room.id)
    capacity = ROOM_TYPES[body.room_type]
    if occupancy > capacity:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Room type cannot hold its current occupants")

    duplicate = await session.execute(
        select(RoomingRoomModel.id).where(
            RoomingRoomModel.hotel_id == hotel.id,
            RoomingRoomModel.room_number == body.room_number.strip(),
            RoomingRoomModel.id != room.id,
        )
    )
    if duplicate.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Room number already exists for this hotel")

    room.room_number = body.room_number.strip()
    room.room_type = body.room_type
    room.capacity = capacity
    room.allocation_tag = body.allocation_tag
    room.roommate_notes = body.roommate_notes.strip() if body.roommate_notes else None
    room.is_saved = body.is_saved
    await session.flush()
    await _audit(session, current_user, request, "rooming.room_updated", hotel, {"room_id": str(room.id)})
    return _room_response(room, [])


@router.put(
    "/hotels/{hotel_id}/rooms/order",
    response_model=list[RoomingRoomResponse],
    summary="Persist the display order of a hotel's rooms",
)
async def update_room_order(
    hotel_id: uuid.UUID,
    body: UpdateRoomOrderRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[RoomingRoomResponse]:
    hotel, _ = await _get_rooming_hotel(session, hotel_id, current_user)
    rooms_result = await session.execute(select(RoomingRoomModel).where(RoomingRoomModel.hotel_id == hotel.id))
    rooms = list(rooms_result.scalars().all())
    room_by_id = {room.id: room for room in rooms}
    if len(body.room_ids) != len(rooms) or set(body.room_ids) != set(room_by_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Room order must include every hotel room once")
    for sort_order, room_id in enumerate(body.room_ids):
        room_by_id[room_id].sort_order = sort_order
    await session.flush()
    await _audit(session, current_user, request, "rooming.rooms_reordered", hotel, {"room_ids": [str(room_id) for room_id in body.room_ids]})
    return [_room_response(room_by_id[room_id], []) for room_id in body.room_ids]


@router.delete(
    "/rooms/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a room and any assignments stored for it",
)
async def delete_room(
    room_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    room, hotel, _ = await _get_room(session, room_id, current_user)
    await session.execute(delete(RoomingAssignmentModel).where(RoomingAssignmentModel.room_id == room.id))
    await _audit(session, current_user, request, "rooming.room_deleted", hotel, {"room_id": str(room.id), "room_number": room.room_number})
    await session.delete(room)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/hotels/{hotel_id}/passengers/{passenger_id}/allocation",
    response_model=RoomingWorkspaceResponse,
    summary="Allocate, move, or unallocate a passenger and save hotel-specific preferences",
)
async def update_passenger_allocation(
    hotel_id: uuid.UUID,
    passenger_id: uuid.UUID,
    body: UpdatePassengerAllocationRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingWorkspaceResponse:
    hotel, group = await _get_rooming_hotel(session, hotel_id, current_user)
    passenger_result = await session.execute(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.id == passenger_id,
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.status.in_(ROOMING_PASSENGER_STATUSES),
        )
    )
    passenger = passenger_result.scalar_one_or_none()
    if not passenger:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passenger was not found in this group")

    preference_result = await session.execute(
        select(RoomingPassengerPreferenceModel)
        .where(RoomingPassengerPreferenceModel.hotel_id == hotel.id, RoomingPassengerPreferenceModel.passenger_id == passenger.id)
        .with_for_update()
    )
    preference = preference_result.scalar_one_or_none()
    if preference is None:
        preference = RoomingPassengerPreferenceModel(hotel_id=hotel.id, passenger_id=passenger.id)
        session.add(preference)
    preference.allocation_tag = body.allocation_tag
    preference.special_requests = body.special_requests
    preference.roommate_notes = body.roommate_notes.strip() if body.roommate_notes else None

    assignment_result = await session.execute(
        select(RoomingAssignmentModel)
        .where(RoomingAssignmentModel.hotel_id == hotel.id, RoomingAssignmentModel.passenger_id == passenger.id)
        .with_for_update()
    )
    assignment = assignment_result.scalar_one_or_none()

    if body.room_id is None:
        if assignment:
            await session.delete(assignment)
    else:
        other_assignments_result = await session.execute(
            select(RoomingAssignmentModel)
            .join(RoomingHotelModel, RoomingAssignmentModel.hotel_id == RoomingHotelModel.id)
            .where(RoomingHotelModel.group_id == group.id, RoomingAssignmentModel.passenger_id == passenger.id, RoomingAssignmentModel.hotel_id != hotel.id)
            .with_for_update()
        )
        for other_assignment in other_assignments_result.scalars().all():
            await session.delete(other_assignment)
        room_result = await session.execute(
            select(RoomingRoomModel).where(RoomingRoomModel.id == body.room_id, RoomingRoomModel.hotel_id == hotel.id).with_for_update()
        )
        room = room_result.scalar_one_or_none()
        if not room:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room was not found for this hotel")
        effective_passenger_tag = body.allocation_tag
        if effective_passenger_tag == "unspecified":
            effective_passenger_tag = _default_rooming_tag(passenger, _family_size(passenger, None))
        if not _passenger_matches_room_allocation(
            effective_passenger_tag,
            body.special_requests,
            room.allocation_tag,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Passenger does not match this room's {room.allocation_tag} allocation",
            )
        if assignment is None or assignment.room_id != room.id:
            occupancy = await _room_occupancy(session, room.id)
            if occupancy >= room.capacity:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Room is already at capacity")
            if assignment is None:
                assignment = RoomingAssignmentModel(hotel_id=hotel.id, room_id=room.id, passenger_id=passenger.id, position=occupancy + 1)
                session.add(assignment)
            else:
                assignment.room_id = room.id
                assignment.position = occupancy + 1
            if occupancy + 1 >= room.capacity:
                room.is_saved = True

    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        "rooming.passenger_allocated",
        hotel,
        {"passenger_id": str(passenger.id), "room_id": str(body.room_id) if body.room_id else None},
    )
    return await _workspace_response(session, group)


@router.get(
    "/hotels/{hotel_id}/export.xlsx",
    summary="Download a hotel-ready rooming list workbook",
)
async def export_hotel_rooming_list(
    hotel_id: uuid.UUID,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    hotel, group = await _get_rooming_hotel(session, hotel_id, current_user)
    rooms_result = await session.execute(
        select(RoomingRoomModel).where(RoomingRoomModel.hotel_id == hotel.id)
    )
    rooms = sorted(rooms_result.scalars().all(), key=lambda room: (room.sort_order, _room_number_sort_key(room.room_number)))
    assignments_result = await session.execute(
        select(RoomingAssignmentModel).where(RoomingAssignmentModel.hotel_id == hotel.id).order_by(RoomingAssignmentModel.position.asc())
    )
    assignments_by_room: dict[uuid.UUID, list[RoomingAssignmentModel]] = defaultdict(list)
    passenger_ids: set[uuid.UUID] = set()
    for assignment in assignments_result.scalars().all():
        assignments_by_room[assignment.room_id].append(assignment)
        passenger_ids.add(assignment.passenger_id)
    passenger_result = await session.execute(select(PassportSubmissionModel).where(PassportSubmissionModel.id.in_(passenger_ids))) if passenger_ids else None
    passengers = list(passenger_result.scalars().all()) if passenger_result else []
    preference_result = await session.execute(select(RoomingPassengerPreferenceModel).where(RoomingPassengerPreferenceModel.hotel_id == hotel.id))
    preferences = {preference.passenger_id: preference for preference in preference_result.scalars().all()}
    content = RoomingExcelExporter().export_hotel(
        group_name=group.name,
        hotel=hotel,
        rooms=[(room, assignments_by_room.get(room.id, [])) for room in rooms],
        passenger_by_id={passenger.id: passenger for passenger in passengers},
        preferences=preferences,
    )
    filename = _export_filename(hotel.hotel_name)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/hotels/{hotel_id}/check-ins", response_model=HotelCheckinDashboardResponse, summary="Get hotel check-in dashboard")
async def get_hotel_checkins(
    hotel_id: uuid.UUID,
    current_user: User = Depends(require_role(CHECKIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> HotelCheckinDashboardResponse:
    hotel, group = await _get_checkin_hotel(session, hotel_id, current_user)
    return await _checkin_dashboard(session, hotel, group)


@router.post("/hotels/{hotel_id}/check-ins/scan", response_model=HotelCheckinScanResponse, summary="Scan a passenger into a hotel")
async def scan_hotel_checkin(
    hotel_id: uuid.UUID,
    body: HotelCheckinScanRequest,
    request: Request,
    current_user: User = Depends(require_role(CHECKIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> HotelCheckinScanResponse:
    hotel, group = await _get_checkin_hotel(session, hotel_id, current_user)
    resolved = await session.execute(
        select(PassportSubmissionModel, PassengerQRTokenModel)
        .join(PassengerQRTokenModel, PassengerQRTokenModel.passenger_id == PassportSubmissionModel.id)
        .where(PassengerQRTokenModel.agency_id == hotel.agency_id, PassengerQRTokenModel.token_hash == qr_hash(body.qr_payload.strip()))
    )
    pair = resolved.first()
    if not pair:
        return HotelCheckinScanResponse(status="invalid", message="Invalid QR code.")
    passenger, token = pair
    now = datetime.now(tz=UTC)
    if token.revoked_at:
        return HotelCheckinScanResponse(status="revoked", message="This passenger QR code has been revoked.")
    if not token.is_active:
        return HotelCheckinScanResponse(status="inactive", message="This passenger QR code is inactive.")
    if token.expires_at <= now:
        return HotelCheckinScanResponse(status="expired", message="This passenger QR code has expired.")
    if passenger.group_id != group.id:
        return HotelCheckinScanResponse(status="wrong_group", message="This passenger belongs to another group.")
    assignment_result = await session.execute(select(RoomingAssignmentModel).where(RoomingAssignmentModel.hotel_id == hotel.id, RoomingAssignmentModel.passenger_id == passenger.id))
    assignment = assignment_result.scalar_one_or_none()
    if not assignment:
        elsewhere = await session.execute(select(RoomingAssignmentModel.id).join(RoomingHotelModel, RoomingHotelModel.id == RoomingAssignmentModel.hotel_id).where(RoomingHotelModel.group_id == group.id, RoomingAssignmentModel.passenger_id == passenger.id))
        message = "Passenger is allocated to a different hotel." if elsewhere.scalar_one_or_none() else "Passenger is not allocated to any room."
        return HotelCheckinScanResponse(status="wrong_hotel" if "different" in message else "unallocated", message=message)
    checkin_result = await session.execute(select(RoomingCheckinModel).where(RoomingCheckinModel.hotel_id == hotel.id, RoomingCheckinModel.passenger_id == passenger.id).with_for_update())
    checkin = checkin_result.scalar_one_or_none()
    already_checked_in = bool(checkin and checkin.checked_in)
    if checkin is None:
        checkin = RoomingCheckinModel(agency_id=hotel.agency_id, hotel_id=hotel.id, room_id=assignment.room_id, passenger_id=passenger.id)
        session.add(checkin)
    checkin.room_id = assignment.room_id
    checkin.checked_in = True
    checkin.checked_in_at = checkin.checked_in_at or now
    checkin.updated_by_user_id = current_user.id
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        "rooming.checkin_scanned",
        hotel,
        {
            "passenger_id": str(passenger.id),
            "checkin_id": str(checkin.id),
            "client_event_id": body.client_event_id,
            "device_id": body.device_id,
            "already_checked_in": already_checked_in,
        },
    )
    item = await _checkin_item(session, hotel, assignment, passenger, checkin)
    return HotelCheckinScanResponse(status="already_checked_in" if already_checked_in else "checked_in", message=f"{passenger.client_name} {'was already checked in' if already_checked_in else 'checked in'}.", checkin=item)


@router.patch("/check-ins/{checkin_id}", response_model=HotelCheckinPassengerResponse, summary="Update hotel key, welcome kit, or remarks")
async def update_hotel_checkin(
    checkin_id: uuid.UUID,
    body: UpdateHotelCheckinRequest,
    request: Request,
    current_user: User = Depends(require_role(CHECKIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> HotelCheckinPassengerResponse:
    result = await session.execute(select(RoomingCheckinModel).where(RoomingCheckinModel.id == checkin_id).with_for_update())
    checkin = result.scalar_one_or_none()
    if not checkin:
        raise HTTPException(status_code=404, detail="Check-in was not found")
    hotel, _ = await _get_checkin_hotel(session, checkin.hotel_id, current_user)
    now = datetime.now(tz=UTC)
    if body.key_issued is not None:
        checkin.key_issued = body.key_issued
        checkin.key_issued_at = now if body.key_issued else None
    if body.welcome_letter_issued is not None:
        checkin.welcome_letter_issued = body.welcome_letter_issued
        checkin.welcome_letter_issued_at = now if body.welcome_letter_issued else None
    if body.remarks is not None:
        checkin.remarks = body.remarks.strip() or None
    checkin.updated_by_user_id = current_user.id
    await session.flush()
    audit_metadata = {"checkin_id": str(checkin.id)}
    if body.key_issued is not None:
        await _audit(session, current_user, request, "rooming.checkin_key_issued", hotel, {**audit_metadata, "issued": body.key_issued})
    if body.welcome_letter_issued is not None:
        await _audit(session, current_user, request, "rooming.checkin_welcome_letter_issued", hotel, {**audit_metadata, "issued": body.welcome_letter_issued})
    if body.remarks is not None:
        await _audit(session, current_user, request, "rooming.checkin_remarks_changed", hotel, audit_metadata)
    assignment = (await session.execute(select(RoomingAssignmentModel).where(RoomingAssignmentModel.hotel_id == hotel.id, RoomingAssignmentModel.passenger_id == checkin.passenger_id))).scalar_one()
    passenger = (await session.execute(select(PassportSubmissionModel).where(PassportSubmissionModel.id == checkin.passenger_id))).scalar_one()
    return await _checkin_item(session, hotel, assignment, passenger, checkin)


@router.get("/hotels/{hotel_id}/check-ins/export.xlsx", summary="Export hotel check-in control sheet")
async def export_hotel_checkins(
    hotel_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    hotel, group = await _get_rooming_hotel(session, hotel_id, current_user)
    dashboard = await _checkin_dashboard(session, hotel, group)
    content = RoomingExcelExporter().export_checkins(group_name=group.name, hotel_name=hotel.hotel_name, passengers=dashboard.passengers)
    await _audit(session, current_user, request, "rooming.checkin_exported", hotel, {})
    return StreamingResponse(io.BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="hotel_checkins_{_export_filename(hotel.hotel_name).removeprefix("rooming_list_")}"'})


async def _get_rooming_group(session: AsyncSession, group_id: uuid.UUID, current_user: User) -> ClientGroupModel:
    result = await session.execute(select(ClientGroupModel).where(ClientGroupModel.id == group_id, ClientGroupModel.status != "deleted"))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")
    if current_user.role == UserRole.AGENCY_COORDINATOR:
        if not await AuthorizationPolicy(session).coordinator_has_group(current_user.id, group.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This group is not assigned to this coordinator")
        return group
    try:
        await AuthorizationPolicy(session).require_view_group(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    return group


async def _get_rooming_hotel(session: AsyncSession, hotel_id: uuid.UUID, current_user: User) -> tuple[RoomingHotelModel, ClientGroupModel]:
    result = await session.execute(select(RoomingHotelModel).where(RoomingHotelModel.id == hotel_id))
    hotel = result.scalar_one_or_none()
    if not hotel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hotel was not found")
    group = await _get_rooming_group(session, hotel.group_id, current_user)
    return hotel, group


async def _get_checkin_hotel(session: AsyncSession, hotel_id: uuid.UUID, current_user: User) -> tuple[RoomingHotelModel, ClientGroupModel]:
    result = await session.execute(select(RoomingHotelModel).where(RoomingHotelModel.id == hotel_id))
    hotel = result.scalar_one_or_none()
    if not hotel:
        raise HTTPException(status_code=404, detail="Hotel was not found")
    group = await _get_rooming_group(session, hotel.group_id, current_user) if current_user.role != UserRole.AGENCY_COORDINATOR else None
    if current_user.role == UserRole.AGENCY_COORDINATOR:
        assigned = await AuthorizationPolicy(session).coordinator_has_group(current_user.id, hotel.group_id)
        if not assigned:
            raise HTTPException(status_code=403, detail="This group is not assigned to this coordinator")
        group = (await session.execute(select(ClientGroupModel).where(ClientGroupModel.id == hotel.group_id))).scalar_one()
    return hotel, group


async def _checkin_dashboard(session: AsyncSession, hotel: RoomingHotelModel, group: ClientGroupModel) -> HotelCheckinDashboardResponse:
    assignments = list((await session.execute(select(RoomingAssignmentModel).where(RoomingAssignmentModel.hotel_id == hotel.id).order_by(RoomingAssignmentModel.position))).scalars().all())
    rooms = {room.id: room for room in (await session.execute(select(RoomingRoomModel).where(RoomingRoomModel.hotel_id == hotel.id))).scalars().all()}
    passenger_ids = [assignment.passenger_id for assignment in assignments]
    passengers = {p.id: p for p in (await session.execute(select(PassportSubmissionModel).where(PassportSubmissionModel.id.in_(passenger_ids)))).scalars().all()} if passenger_ids else {}
    checkins = {c.passenger_id: c for c in (await session.execute(select(RoomingCheckinModel).where(RoomingCheckinModel.hotel_id == hotel.id))).scalars().all()}
    family_sizes = _family_sizes(passengers.values())
    items = [await _checkin_item(session, hotel, assignment, passengers[assignment.passenger_id], checkins.get(assignment.passenger_id), family_sizes) for assignment in assignments if assignment.passenger_id in passengers]
    missing_rooms = sum(1 for room in rooms.values() if 0 < sum(1 for a in assignments if a.room_id == room.id) < room.capacity)
    return HotelCheckinDashboardResponse(hotel_id=hotel.id, hotel_name=hotel.hotel_name, group_id=group.id, group_name=group.name, total_allocated_passengers=len(items), checked_in_count=sum(item.checked_in for item in items), keys_issued_count=sum(item.key_issued for item in items), welcome_letters_issued_count=sum(item.welcome_letter_issued for item in items), rooms_complete=sum(1 for room in rooms.values() if sum(1 for a in assignments if a.room_id == room.id) >= room.capacity), rooms_with_missing_occupants=missing_rooms, passengers=items)


async def _checkin_item(
    session: AsyncSession,
    hotel: RoomingHotelModel,
    assignment: RoomingAssignmentModel,
    passenger: PassportSubmissionModel,
    checkin: RoomingCheckinModel | None,
    family_sizes: dict[uuid.UUID, int] | None = None,
) -> HotelCheckinPassengerResponse:
    room = (await session.execute(select(RoomingRoomModel).where(RoomingRoomModel.id == assignment.room_id))).scalar_one()
    occupants = list((await session.execute(select(RoomingAssignmentModel, PassportSubmissionModel).join(PassportSubmissionModel, PassportSubmissionModel.id == RoomingAssignmentModel.passenger_id).where(RoomingAssignmentModel.room_id == room.id))).all())
    preference = (await session.execute(select(RoomingPassengerPreferenceModel).where(RoomingPassengerPreferenceModel.hotel_id == hotel.id, RoomingPassengerPreferenceModel.passenger_id == passenger.id))).scalar_one_or_none()
    is_vip = room.allocation_tag == "vip" or bool(preference and "vip" in (preference.special_requests or []))
    family_size = _family_size(passenger, family_sizes)
    return HotelCheckinPassengerResponse(checkin_id=checkin.id if checkin else uuid.UUID(int=0), passenger_id=passenger.id, passenger_name=passenger.client_name, submission_mode=passenger.submission_mode, family_group_id=passenger.family_group_id, family_group_label=_family_group_label(passenger, family_size), family_relation=passenger.family_relation, family_size=family_size, family_head_name=passenger.family_head_name, room_id=room.id, room_number=room.room_number, room_type=room.room_type, roommates=[other.client_name for _, other in occupants if other.id != passenger.id], checked_in=bool(checkin and checkin.checked_in), checked_in_at=checkin.checked_in_at if checkin else None, key_issued=bool(checkin and checkin.key_issued), key_issued_at=checkin.key_issued_at if checkin else None, welcome_letter_issued=bool(checkin and checkin.welcome_letter_issued), welcome_letter_issued_at=checkin.welcome_letter_issued_at if checkin else None, remarks=checkin.remarks if checkin else None, is_vip=is_vip, has_special_request=bool(preference and preference.special_requests), room_has_missing_occupants=0 < len(occupants) < room.capacity)


async def _get_room(session: AsyncSession, room_id: uuid.UUID, current_user: User) -> tuple[RoomingRoomModel, RoomingHotelModel, ClientGroupModel]:
    result = await session.execute(select(RoomingRoomModel).where(RoomingRoomModel.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room was not found")
    hotel, group = await _get_rooming_hotel(session, room.hotel_id, current_user)
    return room, hotel, group


async def _next_room_number(session: AsyncSession, hotel_id: uuid.UUID) -> int:
    result = await session.execute(select(RoomingRoomModel.room_number).where(RoomingRoomModel.hotel_id == hotel_id))
    numbers = [int(value) for value in result.scalars().all() if value.isdigit()]
    return max(numbers, default=0) + 1


async def _room_occupancy(session: AsyncSession, room_id: uuid.UUID) -> int:
    result = await session.execute(select(func.count()).select_from(RoomingAssignmentModel).where(RoomingAssignmentModel.room_id == room_id))
    return int(result.scalar_one())


async def _room_count(session: AsyncSession, hotel_id: uuid.UUID) -> int:
    result = await session.execute(select(func.count()).select_from(RoomingRoomModel).where(RoomingRoomModel.hotel_id == hotel_id))
    return int(result.scalar_one())


async def _workspace_response(session: AsyncSession, group: ClientGroupModel) -> RoomingWorkspaceResponse:
    passengers_result = await session.execute(
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.status.in_(ROOMING_PASSENGER_STATUSES),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    passengers = list(passengers_result.scalars().all())
    family_sizes = _family_sizes(passengers)
    hotels_result = await session.execute(
        select(RoomingHotelModel).where(RoomingHotelModel.group_id == group.id).order_by(RoomingHotelModel.created_at.asc())
    )
    hotels = list(hotels_result.scalars().all())
    if not hotels:
        return RoomingWorkspaceResponse(group_id=group.id, group_name=group.name, destination=group.destination, total_passengers=len(passengers), passengers=[_passenger_response(passenger, None, family_sizes) for passenger in passengers])

    hotel_ids = [hotel.id for hotel in hotels]
    rooms_result = await session.execute(select(RoomingRoomModel).where(RoomingRoomModel.hotel_id.in_(hotel_ids)))
    rooms = sorted(rooms_result.scalars().all(), key=lambda room: _room_number_sort_key(room.room_number))
    assignments_result = await session.execute(select(RoomingAssignmentModel).where(RoomingAssignmentModel.hotel_id.in_(hotel_ids)).order_by(RoomingAssignmentModel.position.asc()))
    preferences_result = await session.execute(select(RoomingPassengerPreferenceModel).where(RoomingPassengerPreferenceModel.hotel_id.in_(hotel_ids)))
    preference_by_pair = {(pref.hotel_id, pref.passenger_id): pref for pref in preferences_result.scalars().all()}
    passenger_by_id = {passenger.id: passenger for passenger in passengers}
    occupants_by_room: dict[uuid.UUID, list[RoomingPassengerResponse]] = defaultdict(list)
    allocated_by_hotel: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    allocated_passenger_ids: set[uuid.UUID] = set()
    for assignment in assignments_result.scalars().all():
        passenger = passenger_by_id.get(assignment.passenger_id)
        if passenger:
            occupants_by_room[assignment.room_id].append(_passenger_response(passenger, preference_by_pair.get((assignment.hotel_id, passenger.id)), family_sizes))
            allocated_by_hotel[assignment.hotel_id].add(passenger.id)
            allocated_passenger_ids.add(passenger.id)
    rooms_by_hotel: dict[uuid.UUID, list[RoomingRoomModel]] = defaultdict(list)
    for room in rooms:
        rooms_by_hotel[room.hotel_id].append(room)
    hotel_responses = []
    for hotel in hotels:
        hotel_rooms = rooms_by_hotel[hotel.id]
        hotel_responses.append(
            RoomingHotelResponse(
                id=hotel.id,
                hotel_name=hotel.hotel_name,
                city=hotel.city,
                check_in_date=hotel.check_in_date,
                check_out_date=hotel.check_out_date,
                rooms=[_room_response(room, occupants_by_room[room.id]) for room in hotel_rooms],
                unallocated_passengers=[
                    _passenger_response(passenger, preference_by_pair.get((hotel.id, passenger.id)), family_sizes)
                    for passenger in passengers
                    if passenger.id not in allocated_passenger_ids
                ],
                allocated_passenger_count=len(allocated_by_hotel[hotel.id]),
                capacity_total=sum(room.capacity for room in hotel_rooms),
            )
        )
    default_hotel_id = hotels[0].id
    return RoomingWorkspaceResponse(
        group_id=group.id,
        group_name=group.name,
        destination=group.destination,
        total_passengers=len(passengers),
        hotels=hotel_responses,
        passengers=[_passenger_response(passenger, preference_by_pair.get((default_hotel_id, passenger.id)), family_sizes) for passenger in passengers],
    )


def _passenger_response(passenger: PassportSubmissionModel, preference: RoomingPassengerPreferenceModel | None, family_sizes: dict[uuid.UUID, int] | None = None) -> RoomingPassengerResponse:
    fields = passenger.confirmed_fields or passenger.extracted_fields or {}
    family_size = _family_size(passenger, family_sizes)
    default_tag = _default_rooming_tag(passenger, family_size)
    return RoomingPassengerResponse(
        passenger_id=passenger.id,
        client_name=passenger.client_name,
        client_email=passenger.client_email,
        client_phone=passenger.client_phone,
        passport_sex=fields.get("sex"),
        submission_mode=passenger.submission_mode,
        family_group_id=passenger.family_group_id,
        family_group_label=_family_group_label(passenger, family_size),
        family_member_index=passenger.family_member_index,
        family_relation=passenger.family_relation,
        family_gender=passenger.family_gender,
        family_size=family_size,
        family_head_name=passenger.family_head_name,
        allocation_tag=preference.allocation_tag if preference else default_tag,
        special_requests=preference.special_requests if preference else [],
        roommate_notes=preference.roommate_notes if preference else None,
    )


def _family_sizes(passengers: Iterable[PassportSubmissionModel]) -> dict[uuid.UUID, int]:
    sizes: dict[uuid.UUID, int] = defaultdict(int)
    for passenger in passengers:
        if passenger.family_group_id:
            sizes[passenger.family_group_id] += 1
    return dict(sizes)


def _family_size(passenger: PassportSubmissionModel, family_sizes: dict[uuid.UUID, int] | None) -> int:
    if not passenger.family_group_id:
        return 1
    return max(1, int((family_sizes or {}).get(passenger.family_group_id, 1)))


def _default_rooming_tag(passenger: PassportSubmissionModel, family_size: int) -> str:
    if passenger.submission_mode == "family" and passenger.family_group_id:
        return "couple" if family_size == 2 else "family"
    sex = ((passenger.confirmed_fields or passenger.extracted_fields or {}).get("sex") or "").strip().lower()
    if sex in {"m", "male"}:
        return "male"
    if sex in {"f", "female"}:
        return "female"
    return "unspecified"


def _passenger_matches_room_allocation(
    passenger_tag: str,
    special_requests: list[str],
    room_tag: str,
) -> bool:
    if room_tag == "mixed":
        return True
    if room_tag == "vip":
        return "vip" in special_requests
    return passenger_tag == room_tag


def _family_group_label(passenger: PassportSubmissionModel, family_size: int) -> str | None:
    if passenger.submission_mode != "family" or not passenger.family_group_id:
        return None
    head = passenger.family_head_name or passenger.client_name
    kind = "Couple" if family_size == 2 else "Family"
    return f"{head} {kind} ({family_size})"


def _room_response(room: RoomingRoomModel, occupants: list[RoomingPassengerResponse]) -> RoomingRoomResponse:
    return RoomingRoomResponse(
        id=room.id,
        room_number=room.room_number,
        room_type=room.room_type,
        capacity=room.capacity,
        allocation_tag=room.allocation_tag,
        roommate_notes=room.roommate_notes,
        is_saved=room.is_saved,
        sort_order=room.sort_order,
        occupants=occupants,
    )


async def _audit(session: AsyncSession, current_user: User, request: Request, action: str, hotel: RoomingHotelModel, metadata: dict[str, object]) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type="rooming_hotel",
        agency_id=hotel.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(hotel.id),
        ip_address=request.client.host if request.client else None,
        metadata=metadata,
    )


def _export_filename(hotel_name: str) -> str:
    normalized = "".join(character if character.isalnum() else "_" for character in hotel_name).strip("_")
    return f"rooming_list_{normalized or 'hotel'}.xlsx"


def _room_number_sort_key(room_number: str) -> tuple[int, str]:
    match = re.match(r"^(\d+)(.*)$", room_number.strip())
    if not match:
        return (10**9, room_number.casefold())
    return (int(match.group(1)), match.group(2).casefold())
