"""Hotel rooming: access."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.rooming.auto_allocator import PlannedRoom
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingHotelModel,
    RoomingHotelPassengerModel,
    RoomingRoomModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.presentation.api.v1.routes.rooming_allocation_support import (
    room_number_sort_key as _room_number_sort_key,
)
from app.presentation.security.client_ip import trusted_client_ip

from .rooming_policy import ROOMING_PASSENGER_STATUSES


async def _get_rooming_group(
    session: AsyncSession, group_id: uuid.UUID, current_user: User
) -> ClientGroupModel:
    result = await session.execute(
        select(ClientGroupModel).where(
            ClientGroupModel.id == group_id, ClientGroupModel.status != "deleted"
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")
    if current_user.role == UserRole.AGENCY_COORDINATOR:
        if current_user.agency_id != group.agency_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This group is not assigned to this coordinator",
            )
        if not await AuthorizationPolicy(session).coordinator_has_group(current_user.id, group.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This group is not assigned to this coordinator",
            )
        return group
    try:
        await AuthorizationPolicy(session).require_view_group(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    return group


async def _get_rooming_hotel(
    session: AsyncSession, hotel_id: uuid.UUID, current_user: User
) -> tuple[RoomingHotelModel, ClientGroupModel]:
    result = await session.execute(
        select(RoomingHotelModel).where(RoomingHotelModel.id == hotel_id)
    )
    hotel = result.scalar_one_or_none()
    if not hotel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hotel was not found")
    group = await _get_rooming_group(session, hotel.group_id, current_user)
    if hotel.agency_id != group.agency_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotel was not found",
        )
    return hotel, group


async def _get_checkin_hotel(
    session: AsyncSession, hotel_id: uuid.UUID, current_user: User
) -> tuple[RoomingHotelModel, ClientGroupModel]:
    return await _get_rooming_hotel(session, hotel_id, current_user)


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
            operational_roster_member(),
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
        statement = statement.with_for_update(read=True).execution_options(populate_existing=True)
    return list((await session.execute(statement)).scalars().all())


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
                    PassportSubmissionModel.id == RoomingHotelPassengerModel.passenger_id,
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
    if not locked_hotel.allocation_fingerprint or locked_hotel.allocation_updated_at is None:
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


def _datetime_is_after(value: datetime, baseline: datetime) -> bool:
    """Compare database timestamps consistently across SQLite/PostgreSQL tests."""

    normalized_value = value if value.tzinfo else value.replace(tzinfo=UTC)
    normalized_baseline = baseline if baseline.tzinfo else baseline.replace(tzinfo=UTC)
    return normalized_value > normalized_baseline


async def _stored_room_plan_matches(
    session: AsyncSession,
    hotel_id: uuid.UUID,
    expected: list[PlannedRoom],
) -> bool:
    rooms = sorted(
        (
            (
                await session.execute(
                    select(RoomingRoomModel).where(RoomingRoomModel.hotel_id == hotel_id)
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


async def _audit(
    session: AsyncSession,
    current_user: User,
    request: Request,
    action: str,
    hotel: RoomingHotelModel,
    metadata: Mapping[str, object],
) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type="rooming_hotel",
        agency_id=hotel.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(hotel.id),
        ip_address=trusted_client_ip(request),
        metadata=dict(metadata),
    )


def _export_filename(hotel_name: str) -> str:
    normalized = "".join(
        character if character.isalnum() else "_" for character in hotel_name
    ).strip("_")
    return f"rooming_list_{normalized or 'hotel'}.xlsx"
