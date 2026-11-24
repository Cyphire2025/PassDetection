"""Hotel rooming: checkins."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    PassengerQRTokenModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingCheckinModel,
    RoomingHotelModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.presentation.api.v1.routes.tour_operations_qr_helpers import qr_hash
from app.presentation.api.v1.schemas.rooming_schemas import (
    HotelCheckinDashboardResponse,
    HotelCheckinPassengerResponse,
    HotelCheckinScanRequest,
    HotelCheckinScanResponse,
    UpdateHotelCheckinRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

from .rooming_access import _audit, _get_checkin_hotel, _require_current_allocation
from .rooming_checkin_reads import _checkin_dashboard, _checkin_item
from .rooming_policy import CHECKIN_ROLES, ROOMING_PASSENGER_STATUSES

router = APIRouter()


@router.get(
    "/hotels/{hotel_id}/check-ins",
    response_model=HotelCheckinDashboardResponse,
    summary="Get hotel check-in dashboard",
)
async def get_hotel_checkins(
    hotel_id: uuid.UUID,
    current_user: User = Depends(require_role(CHECKIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> HotelCheckinDashboardResponse:
    hotel, group = await _get_checkin_hotel(session, hotel_id, current_user)
    await _require_current_allocation(session, hotel)
    return await _checkin_dashboard(session, hotel, group)


@router.post(
    "/hotels/{hotel_id}/check-ins/scan",
    response_model=HotelCheckinScanResponse,
    summary="Scan a passenger into a hotel",
    dependencies=[Depends(require_cookie_csrf)],
)
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
        .join(
            PassengerQRTokenModel, PassengerQRTokenModel.passenger_id == PassportSubmissionModel.id
        )
        .where(
            PassengerQRTokenModel.agency_id == hotel.agency_id,
            PassengerQRTokenModel.token_hash == qr_hash(body.qr_payload.strip()),
            PassportSubmissionModel.agency_id == hotel.agency_id,
            PassportSubmissionModel.status.in_(ROOMING_PASSENGER_STATUSES),
            operational_roster_member(),
        )
    )
    pair = resolved.first()
    if not pair:
        return HotelCheckinScanResponse(status="invalid", message="Invalid QR code.")
    passenger, token = pair
    now = datetime.now(tz=UTC)
    if token.revoked_at:
        return HotelCheckinScanResponse(
            status="revoked", message="This passenger QR code has been revoked."
        )
    if not token.is_active:
        return HotelCheckinScanResponse(
            status="inactive", message="This passenger QR code is inactive."
        )
    if token.expires_at <= now:
        return HotelCheckinScanResponse(
            status="expired", message="This passenger QR code has expired."
        )
    if passenger.group_id != group.id:
        return HotelCheckinScanResponse(
            status="wrong_group", message="This passenger belongs to another group."
        )
    assignment_result = await session.execute(
        select(RoomingAssignmentModel)
        .where(
            RoomingAssignmentModel.hotel_id == hotel.id,
            RoomingAssignmentModel.passenger_id == passenger.id,
        )
        .with_for_update()
    )
    assignment = assignment_result.scalar_one_or_none()
    if not assignment:
        elsewhere = await session.execute(
            select(RoomingAssignmentModel.id)
            .join(RoomingHotelModel, RoomingHotelModel.id == RoomingAssignmentModel.hotel_id)
            .where(
                RoomingHotelModel.group_id == group.id,
                RoomingAssignmentModel.passenger_id == passenger.id,
            )
        )
        message = (
            "Passenger is allocated to a different hotel."
            if elsewhere.scalar_one_or_none()
            else "Passenger is not allocated to any room."
        )
        return HotelCheckinScanResponse(
            status="wrong_hotel" if "different" in message else "unallocated", message=message
        )
    checkin_result = await session.execute(
        select(RoomingCheckinModel)
        .where(
            RoomingCheckinModel.hotel_id == hotel.id,
            RoomingCheckinModel.passenger_id == passenger.id,
        )
        .with_for_update()
    )
    checkin = checkin_result.scalar_one_or_none()
    already_checked_in = bool(checkin and checkin.checked_in)
    if checkin is None:
        checkin = RoomingCheckinModel(
            agency_id=hotel.agency_id,
            hotel_id=hotel.id,
            room_id=assignment.room_id,
            passenger_id=passenger.id,
        )
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
    return HotelCheckinScanResponse(
        status="already_checked_in" if already_checked_in else "checked_in",
        message=f"{passenger.client_name} {'was already checked in' if already_checked_in else 'checked in'}.",
        checkin=item,
    )


@router.patch(
    "/check-ins/{checkin_id}",
    response_model=HotelCheckinPassengerResponse,
    summary="Update hotel key, welcome kit, or remarks",
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_hotel_checkin(
    checkin_id: uuid.UUID,
    body: UpdateHotelCheckinRequest,
    request: Request,
    current_user: User = Depends(require_role(CHECKIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> HotelCheckinPassengerResponse:
    result = await session.execute(
        select(RoomingCheckinModel).where(RoomingCheckinModel.id == checkin_id).with_for_update()
    )
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
        await _audit(
            session,
            current_user,
            request,
            "rooming.checkin_key_issued",
            hotel,
            {**audit_metadata, "issued": body.key_issued},
        )
    if body.welcome_letter_issued is not None:
        await _audit(
            session,
            current_user,
            request,
            "rooming.checkin_welcome_letter_issued",
            hotel,
            {**audit_metadata, "issued": body.welcome_letter_issued},
        )
    if body.remarks is not None:
        await _audit(
            session, current_user, request, "rooming.checkin_remarks_changed", hotel, audit_metadata
        )
    assignment = (
        await session.execute(
            select(RoomingAssignmentModel).where(
                RoomingAssignmentModel.hotel_id == hotel.id,
                RoomingAssignmentModel.passenger_id == checkin.passenger_id,
            )
        )
    ).scalar_one()
    passenger = (
        await session.execute(
            select(PassportSubmissionModel).where(
                PassportSubmissionModel.id == checkin.passenger_id,
                PassportSubmissionModel.group_id == hotel.group_id,
                PassportSubmissionModel.agency_id == hotel.agency_id,
            )
        )
    ).scalar_one()
    return await _checkin_item(session, hotel, assignment, passenger, checkin)
