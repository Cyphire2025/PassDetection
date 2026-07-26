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
from app.application.use_cases.rooming.auto_allocator import (
    PlannedRoom,
    RoomingAllocationCandidate,
    build_room_plan,
    normalize_priority_value,
    normalize_rooming_gender,
    room_plan_fingerprint,
)
from app.domain.entities.entities import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingCheckinModel,
    RoomingHotelModel,
    RoomingHotelPassengerModel,
    RoomingPassengerPreferenceModel,
    RoomingRoomModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.rooming_excel_exporter import RoomingExcelExporter
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.rooming.priority_fields import (
    MAX_ROOMING_PRIORITY_FIELDS,
    ROOMING_GENDER_RULE,
    build_rooming_priority_context,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import qr_hash
from app.presentation.api.v1.schemas.rooming_schemas import (
    AutoAllocateRoomsRequest,
    CreateRoomBatchRequest,
    CreateRoomingHotelRequest,
    HotelCheckinDashboardResponse,
    HotelCheckinPassengerResponse,
    HotelCheckinScanRequest,
    HotelCheckinScanResponse,
    RoomingHotelResponse,
    RoomingPassengerResponse,
    RoomingPriorityFieldOptionsResponse,
    RoomingPriorityFieldResponse,
    RoomingRoomResponse,
    RoomingWorkspaceResponse,
    UpdateHotelCheckinRequest,
    UpdateHotelPassengerSelectionRequest,
    UpdateHotelVipRequest,
    UpdatePassengerAllocationRequest,
    UpdateRoomingHotelRequest,
    UpdateRoomOrderRequest,
    UpdateRoomRequest,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()
ROOMING_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF]
CHECKIN_ROLES = [*ROOMING_ROLES, UserRole.AGENCY_COORDINATOR]
ROOMING_PASSENGER_STATUSES = OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES


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
    )
    return RoomingPriorityFieldOptionsResponse(
        group_id=group.id,
        fields=[
            RoomingPriorityFieldResponse.model_validate(field)
            for field in context.fields
        ],
        max_priority_fields=MAX_ROOMING_PRIORITY_FIELDS,
        gender_rule=ROOMING_GENDER_RULE,
    )


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


@router.put(
    "/hotels/{hotel_id}/passenger-selection",
    response_model=RoomingWorkspaceResponse,
    summary="Select, move, or remove hotel passengers in one transaction",
)
async def update_hotel_passenger_selection(
    hotel_id: uuid.UUID,
    body: UpdateHotelPassengerSelectionRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingWorkspaceResponse:
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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
    membership_by_passenger = {
        membership.passenger_id: membership for membership in memberships
    }
    current_ids = {
        membership.passenger_id
        for membership in memberships
        if membership.hotel_id == hotel.id
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
    affected_hotel_ids = {hotel.id} if changed_ids else set()
    affected_hotel_ids.update(
        membership_by_passenger[passenger_id].hotel_id
        for passenger_id in moved_ids
    )
    if affected_hotel_ids:
        await _clear_room_plans(
            session,
            hotel_ids=affected_hotel_ids,
            block_if_checkins=True,
        )

    for passenger_id in removed_ids:
        membership = membership_by_passenger[passenger_id]
        await session.delete(membership)
    for passenger_id in added_ids:
        membership = membership_by_passenger.get(passenger_id)
        if membership is None:
            session.add(
                RoomingHotelPassengerModel(
                    agency_id=group.agency_id,
                    group_id=group.id,
                    hotel_id=hotel.id,
                    passenger_id=passenger_id,
                )
            )
        else:
            membership.agency_id = group.agency_id
            membership.group_id = group.id
            membership.hotel_id = hotel.id
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
                "passenger_ids": [str(value) for value in body.passenger_ids],
            },
        )
    return await _workspace_response(session, group)


@router.put(
    "/hotels/{hotel_id}/vip",
    response_model=RoomingWorkspaceResponse,
    summary="Mark selected hotel passengers as VIP or non-VIP",
)
async def update_hotel_vip_status(
    hotel_id: uuid.UUID,
    body: UpdateHotelVipRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingWorkspaceResponse:
    hotel, group = await _get_rooming_hotel(session, hotel_id, current_user)
    hotel, group = await _lock_rooming_scope(session, hotel, group)
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="VIP status can be changed only for passengers selected for this hotel.",
        )
    changed = [
        membership
        for membership in memberships
        if membership.is_vip is not body.is_vip
    ]
    if changed:
        await _clear_room_plans(
            session,
            hotel_ids={hotel.id},
            block_if_checkins=True,
        )
        for membership in changed:
            membership.is_vip = body.is_vip
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
                "passenger_ids": [str(value) for value in body.passenger_ids],
            },
        )
    return await _workspace_response(session, group)


@router.post(
    "/hotels/{hotel_id}/auto-allocate",
    response_model=RoomingWorkspaceResponse,
    summary="Automatically create gender-safe single and twin rooms",
)
async def auto_allocate_hotel_rooms(
    hotel_id: uuid.UUID,
    body: AutoAllocateRoomsRequest,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> RoomingWorkspaceResponse:
    hotel, group = await _get_rooming_hotel(session, hotel_id, current_user)
    hotel, group = await _lock_rooming_scope(session, hotel, group)
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
        lock_inputs=True,
    )
    catalog_by_key = {field["key"]: field for field in context.fields}
    unknown_fields = [
        key for key in body.priority_fields if key not in catalog_by_key
    ]
    if unknown_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
    if (
        hotel.allocation_fingerprint == fingerprint
        and await _stored_room_plan_matches(session, hotel.id, plan)
    ):
        hotel.allocation_priority_fields = selected_fields
        hotel.allocation_updated_at = datetime.now(tz=UTC)
        await session.flush()
        return await _workspace_response(session, group)

    await _clear_room_plans(
        session,
        hotel_ids={hotel.id},
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
    hotel.allocation_revision += 1
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
                room.room_type == "twin" and len(room.passenger_ids) == 1
                for room in plan
            ),
        },
    )
    return await _workspace_response(session, group)


@router.patch(
    "/hotels/{hotel_id}",
    response_model=RoomingHotelResponse,
    summary="Update hotel stay details",
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
    await _audit(session, current_user, request, "rooming.hotel_updated", hotel, {"room_count": body.room_count})
    workspace = await _workspace_response(session, group)
    return next(item for item in workspace.hotels if item.id == hotel.id)


@router.post(
    "/hotels/{hotel_id}/rooms/generate",
    response_model=list[RoomingRoomResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Generate sequential single, twin, or triple rooms",
    include_in_schema=False,
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


@router.get(
    "/hotels/{hotel_id}/export.xlsx",
    summary="Download a hotel-ready rooming list workbook",
)
async def export_hotel_rooming_list(
    hotel_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    hotel, group = await _get_rooming_hotel(session, hotel_id, current_user)
    await _require_current_allocation(session, hotel)
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
    all_passengers = await _eligible_group_passengers(
        session,
        group,
        lock_for_allocation=True,
    )
    priority_context = await build_rooming_priority_context(
        session,
        group=group,
        passengers=all_passengers,
        required_fields=list(hotel.allocation_priority_fields or []),
        lock_inputs=True,
    )
    memberships = list(
        (
            await session.execute(
                select(RoomingHotelPassengerModel).where(
                    RoomingHotelPassengerModel.hotel_id == hotel.id
                )
            )
        )
        .scalars()
        .all()
    )
    priority_fields = list(hotel.allocation_priority_fields or [])
    if hotel.allocation_fingerprint != "0" * 64:
        export_passenger_by_id = {
            passenger.id: passenger for passenger in all_passengers
        }
        candidates: list[RoomingAllocationCandidate] = []
        for membership in memberships:
            passenger = export_passenger_by_id.get(membership.passenger_id)
            if passenger is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "The selected passenger data changed. Run auto room "
                        "allocation again before exporting."
                    ),
                )
            passport_fields = (
                passenger.confirmed_fields or passenger.extracted_fields or {}
            )
            gender = normalize_rooming_gender(passport_fields.get("sex"))
            if gender is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "A selected passenger no longer has Gender set to Male "
                        "or Female. Correct it and run auto room allocation again."
                    ),
                )
            passenger_values = priority_context.values_by_passenger.get(
                passenger.id,
                {},
            )
            candidates.append(
                RoomingAllocationCandidate(
                    passenger_id=passenger.id,
                    gender=gender,
                    is_vip=membership.is_vip,
                    priority_values=tuple(
                        normalize_priority_value(
                            passenger_values.get(field["key"])
                        )
                        for field in priority_fields
                    ),
                    stable_order=(
                        passenger.created_at,
                        passenger.family_member_index or 0,
                        passenger.client_name.casefold(),
                    ),
                )
            )
        expected_plan = build_room_plan(
            candidates,
            priority_count=len(priority_fields),
        )
        expected_fingerprint = room_plan_fingerprint(
            expected_plan,
            priority_fields,
            candidates=candidates,
        )
        if (
            expected_fingerprint != hotel.allocation_fingerprint
            or not await _stored_room_plan_matches(
                session,
                hotel.id,
                expected_plan,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Passenger grouping inputs changed after room allocation. "
                    "Run auto room allocation again before exporting."
                ),
            )
    content = RoomingExcelExporter().export_hotel(
        group=group,
        hotel=hotel,
        rooms=[(room, assignments_by_room.get(room.id, [])) for room in rooms],
        passenger_by_id={passenger.id: passenger for passenger in passengers},
        vip_passenger_ids={
            membership.passenger_id
            for membership in memberships
            if membership.is_vip
        },
        priority_fields=priority_fields,
        priority_values=priority_context.values_by_passenger,
    )
    await _audit(
        session,
        current_user,
        request,
        "rooming.rooming_list_exported",
        hotel,
        {
            "allocation_revision": hotel.allocation_revision,
            "passenger_count": len(passengers),
            "priority_fields": [
                field.get("key")
                for field in (hotel.allocation_priority_fields or [])
            ],
        },
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
    await _require_current_allocation(session, hotel)
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
    await _require_current_allocation(session, hotel)
    resolved = await session.execute(
        select(PassportSubmissionModel, PassengerQRTokenModel)
        .join(PassengerQRTokenModel, PassengerQRTokenModel.passenger_id == PassportSubmissionModel.id)
        .where(
            PassengerQRTokenModel.agency_id == hotel.agency_id,
            PassengerQRTokenModel.token_hash == qr_hash(body.qr_payload.strip()),
            PassportSubmissionModel.status.in_(ROOMING_PASSENGER_STATUSES),
        )
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
    await _require_current_allocation(session, hotel)
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
    await _require_current_allocation(session, hotel)
    dashboard = await _checkin_dashboard(session, hotel, group)
    content = RoomingExcelExporter().export_checkins(group_name=group.name, hotel_name=hotel.hotel_name, passengers=dashboard.passengers)
    await _audit(session, current_user, request, "rooming.checkin_exported", hotel, {})
    return StreamingResponse(io.BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="hotel_checkins_{_export_filename(hotel.hotel_name).removeprefix("rooming_list_")}"'})


async def _require_current_allocation(
    session: AsyncSession,
    hotel: RoomingHotelModel,
) -> None:
    locked_hotel = (
        await session.execute(
            select(RoomingHotelModel)
            .where(RoomingHotelModel.id == hotel.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if locked_hotel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotel was not found",
        )
    selected_rows = list(
        (
            await session.execute(
                select(
                    RoomingHotelPassengerModel.passenger_id,
                    PassportSubmissionModel.updated_at,
                    PassportSubmissionModel.group_id,
                    PassportSubmissionModel.agency_id,
                    PassportSubmissionModel.status,
                )
                .join(
                    PassportSubmissionModel,
                    PassportSubmissionModel.id
                    == RoomingHotelPassengerModel.passenger_id,
                )
                .where(RoomingHotelPassengerModel.hotel_id == hotel.id)
                .with_for_update(read=True)
            )
        ).all()
    )
    selected_ids = [row.passenger_id for row in selected_rows]
    if not selected_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Select passengers for this hotel and run auto room allocation "
                "before exporting or starting check-in."
            ),
        )
    if (
        not locked_hotel.allocation_fingerprint
        or locked_hotel.allocation_updated_at is None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This hotel's passenger selection changed. Run auto room "
                "allocation before exporting or starting check-in."
            ),
        )
    invalid_selected_count = sum(
        row.group_id != locked_hotel.group_id
        or row.agency_id != locked_hotel.agency_id
        or row.status not in ROOMING_PASSENGER_STATUSES
        for row in selected_rows
    )
    if invalid_selected_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{invalid_selected_count} selected passenger record(s) are no "
                "longer eligible. Refresh the selection and run auto allocation again."
            ),
        )
    changed_passenger_count = sum(
        _datetime_is_after(row.updated_at, locked_hotel.allocation_updated_at)
        for row in selected_rows
    )
    if changed_passenger_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{changed_passenger_count} selected passenger record(s) changed "
                "after room allocation. Run auto room allocation again."
            ),
        )
    assigned_ids = list(
        (
            await session.execute(
                select(RoomingAssignmentModel.passenger_id).where(
                    RoomingAssignmentModel.hotel_id == hotel.id
                )
            )
        ).scalars()
    )
    if len(assigned_ids) != len(selected_ids) or set(assigned_ids) != set(selected_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This hotel's stored rooms no longer match its passenger selection. "
                "Run auto room allocation again."
            ),
        )


async def _eligible_group_passengers(
    session: AsyncSession,
    group: ClientGroupModel,
    *,
    passenger_ids: set[uuid.UUID] | None = None,
    lock_for_allocation: bool = False,
) -> list[PassportSubmissionModel]:
    statement = (
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.status.in_(ROOMING_PASSENGER_STATUSES),
        )
        .order_by(
            PassportSubmissionModel.created_at.asc(),
            PassportSubmissionModel.id.asc(),
        )
    )
    if passenger_ids is not None:
        if not passenger_ids:
            return []
        statement = statement.where(PassportSubmissionModel.id.in_(passenger_ids))
    if lock_for_allocation:
        statement = statement.with_for_update(read=True).execution_options(
            populate_existing=True
        )
    return list((await session.execute(statement)).scalars().all())


async def _lock_rooming_scope(
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


async def _clear_room_plans(
    session: AsyncSession,
    *,
    hotel_ids: set[uuid.UUID],
    block_if_checkins: bool,
) -> None:
    """Invalidate generated rooms without ever erasing check-in history."""

    if not hotel_ids:
        return
    hotels = list(
        (
            await session.execute(
                select(RoomingHotelModel)
                .where(RoomingHotelModel.id.in_(hotel_ids))
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
                    "Room allocation cannot be changed after hotel check-in "
                    "activity has started."
                ),
            )
    await session.execute(
        delete(RoomingAssignmentModel).where(
            RoomingAssignmentModel.hotel_id.in_(hotel_ids)
        )
    )
    await session.execute(
        delete(RoomingRoomModel).where(RoomingRoomModel.hotel_id.in_(hotel_ids))
    )
    for item in hotels:
        item.allocation_fingerprint = None
        item.allocation_updated_at = None
    await session.flush()


async def _stored_room_plan_matches(
    session: AsyncSession,
    hotel_id: uuid.UUID,
    expected: list[PlannedRoom],
) -> bool:
    rooms = sorted(
        (
            (
                await session.execute(
                    select(RoomingRoomModel).where(
                        RoomingRoomModel.hotel_id == hotel_id
                    )
                )
            )
            .scalars()
            .all()
        ),
        key=lambda room: (room.sort_order, _room_number_sort_key(room.room_number)),
    )
    if len(rooms) != len(expected):
        return False
    assignments = list(
        (
            await session.execute(
                select(RoomingAssignmentModel)
                .where(RoomingAssignmentModel.hotel_id == hotel_id)
                .order_by(
                    RoomingAssignmentModel.room_id.asc(),
                    RoomingAssignmentModel.position.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    occupants_by_room: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for assignment in assignments:
        occupants_by_room[assignment.room_id].append(assignment.passenger_id)
    return all(
        room.room_type == planned.room_type
        and room.allocation_tag == planned.allocation_tag
        and tuple(occupants_by_room[room.id]) == planned.passenger_ids
        for room, planned in zip(rooms, expected, strict=True)
    )


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


async def _workspace_response(session: AsyncSession, group: ClientGroupModel) -> RoomingWorkspaceResponse:
    passengers = await _eligible_group_passengers(session, group)
    passengers.sort(key=lambda passenger: (passenger.client_name.casefold(), str(passenger.id)))
    family_sizes = _family_sizes(passengers)
    hotels_result = await session.execute(
        select(RoomingHotelModel).where(RoomingHotelModel.group_id == group.id).order_by(RoomingHotelModel.created_at.asc())
    )
    hotels = list(hotels_result.scalars().all())
    if not hotels:
        return RoomingWorkspaceResponse(
            group_id=group.id,
            group_name=group.name,
            destination=group.destination,
            total_passengers=len(passengers),
            passengers=[
                _passenger_response(passenger, None, family_sizes)
                for passenger in passengers
            ],
        )

    hotel_ids = [hotel.id for hotel in hotels]
    rooms_result = await session.execute(select(RoomingRoomModel).where(RoomingRoomModel.hotel_id.in_(hotel_ids)))
    rooms = sorted(rooms_result.scalars().all(), key=lambda room: _room_number_sort_key(room.room_number))
    assignments_result = await session.execute(select(RoomingAssignmentModel).where(RoomingAssignmentModel.hotel_id.in_(hotel_ids)).order_by(RoomingAssignmentModel.position.asc()))
    preferences_result = await session.execute(select(RoomingPassengerPreferenceModel).where(RoomingPassengerPreferenceModel.hotel_id.in_(hotel_ids)))
    preference_by_pair = {(pref.hotel_id, pref.passenger_id): pref for pref in preferences_result.scalars().all()}
    membership_result = await session.execute(
        select(RoomingHotelPassengerModel).where(
            RoomingHotelPassengerModel.group_id == group.id
        )
    )
    memberships = list(membership_result.scalars().all())
    membership_by_passenger = {
        membership.passenger_id: membership for membership in memberships
    }
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
        passenger = passenger_by_id.get(assignment.passenger_id)
        if passenger:
            membership = membership_by_passenger.get(passenger.id)
            occupants_by_room[assignment.room_id].append(
                _passenger_response(
                    passenger,
                    preference_by_pair.get((assignment.hotel_id, passenger.id)),
                    family_sizes,
                    membership=membership,
                    selected_hotel_name=(
                        hotel_name_by_id.get(membership.hotel_id)
                        if membership
                        else None
                    ),
                )
            )
            allocated_by_hotel[assignment.hotel_id].add(passenger.id)
            allocated_passenger_ids.add(passenger.id)
    rooms_by_hotel: dict[uuid.UUID, list[RoomingRoomModel]] = defaultdict(list)
    for room in rooms:
        rooms_by_hotel[room.hotel_id].append(room)
    default_hotel_id = hotels[0].id
    unallocated_responses: list[RoomingPassengerResponse] = []
    for passenger in passengers:
        if passenger.id in allocated_passenger_ids:
            continue
        membership = membership_by_passenger.get(passenger.id)
        preference_hotel_id = membership.hotel_id if membership else default_hotel_id
        unallocated_responses.append(
            _passenger_response(
                passenger,
                preference_by_pair.get((preference_hotel_id, passenger.id)),
                family_sizes,
                membership=membership,
                selected_hotel_name=(
                    hotel_name_by_id.get(membership.hotel_id)
                    if membership
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
                        preference_by_pair.get(
                            (hotel.id, membership.passenger_id)
                        ),
                        family_sizes,
                        membership=membership,
                        selected_hotel_name=hotel.hotel_name,
                    )
                    for membership in hotel_memberships
                    if membership.passenger_id in passenger_by_id
                ],
                selected_passenger_count=sum(
                    membership.passenger_id in passenger_by_id
                    for membership in hotel_memberships
                ),
                allocation_priority_fields=list(
                    hotel.allocation_priority_fields or []
                ),
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


def _passenger_response(
    passenger: PassportSubmissionModel,
    preference: RoomingPassengerPreferenceModel | None,
    family_sizes: dict[uuid.UUID, int] | None = None,
    *,
    membership: RoomingHotelPassengerModel | None = None,
    selected_hotel_name: str | None = None,
) -> RoomingPassengerResponse:
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
        selected_hotel_id=membership.hotel_id if membership else None,
        selected_hotel_name=selected_hotel_name,
        is_vip=bool(membership and membership.is_vip),
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


def _datetime_is_after(value: datetime, baseline: datetime) -> bool:
    """Compare database timestamps consistently across SQLite/PostgreSQL tests."""

    normalized_value = value if value.tzinfo else value.replace(tzinfo=UTC)
    normalized_baseline = (
        baseline if baseline.tzinfo else baseline.replace(tzinfo=UTC)
    )
    return normalized_value > normalized_baseline


def _allocation_state_is_current(
    *,
    hotel: RoomingHotelModel,
    membership_count: int,
    selected_ids: set[uuid.UUID],
    assigned_ids: set[uuid.UUID],
    assignment_count: int,
    passenger_by_id: dict[uuid.UUID, PassportSubmissionModel],
) -> bool:
    """Apply the same persisted-plan invariants exposed by the guarded routes."""

    if (
        not selected_ids
        or membership_count != len(selected_ids)
        or not hotel.allocation_fingerprint
        or hotel.allocation_updated_at is None
        or assignment_count != len(selected_ids)
        or assigned_ids != selected_ids
    ):
        return False
    return all(
        passenger_id in passenger_by_id
        and not _datetime_is_after(
            passenger_by_id[passenger_id].updated_at,
            hotel.allocation_updated_at,
        )
        for passenger_id in selected_ids
    )


def _room_number_sort_key(room_number: str) -> tuple[int, str]:
    match = re.match(r"^(\d+)(.*)$", room_number.strip())
    if not match:
        return (10**9, room_number.casefold())
    return (int(match.group(1)), match.group(2).casefold())
