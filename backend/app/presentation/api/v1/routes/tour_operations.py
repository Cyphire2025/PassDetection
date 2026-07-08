"""
Tour Operations Routes
======================
Coordinator account and group-assignment operations.
"""

from __future__ import annotations

import uuid
from hashlib import sha256
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.password import hash_password
from app.domain.entities.entities import PassportProcessingStatus, User, UserRole
from app.infrastructure.database.models import (
    AttendanceRecordModel,
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    ManagerGroupAccessModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AssignedPassengerResponse,
    AssignGroupCoordinatorsRequest,
    AssignGroupPassengersRequest,
    AttendanceScanRequest,
    AttendanceScanResponse,
    AttendanceSessionResponse,
    AttendanceCoordinatorSummary,
    AttendanceMissingPassenger,
    AttendanceSessionSummary,
    CreateAttendanceSessionRequest,
    CoordinatorResponse,
    CreateCoordinatorRequest,
    GroupAttendanceOverviewResponse,
    GroupCoordinatorAssignmentResponse,
    GroupPassengerQrCodeResponse,
    GroupPassengerQrCodesResponse,
    TourOperationsArchitectureResponse,
    TourOperationsGroupResponse,
    TourOperationsPhaseResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()

TOUR_OPERATION_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_STAFF,
    UserRole.AGENCY_COORDINATOR,
]
COORDINATOR_MANAGEMENT_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_STAFF,
]
SUBMITTED_PASSENGER_STATUSES = (
    PassportProcessingStatus.CLIENT_SUBMITTED.value,
    PassportProcessingStatus.CONFIRMED.value,
)
ACTIVE_ATTENDANCE_STATUSES = ("draft", "active")


def _require_agency(current_user: User) -> uuid.UUID:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is not assigned to an agency")
    return current_user.agency_id


@router.get(
    "/architecture",
    response_model=TourOperationsArchitectureResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Tour Operations module architecture status",
)
async def get_tour_operations_architecture(
    current_user: User = Depends(require_role(TOUR_OPERATION_ROLES)),
) -> TourOperationsArchitectureResponse:
    return TourOperationsArchitectureResponse(
        module="tour_operations",
        current_phase=8,
        principles=[
            "Coordinator-led operations, not vehicle management.",
            "QR codes contain opaque revocable tokens only.",
            "Attendance is stored separately from passport extraction data.",
            "Offline scan events must be idempotent before scanner rollout.",
            "Coordinator access is isolated from passport and admin workflows.",
        ],
        permissions={
            "agency_coordinator": [
                "assigned_groups",
                "assigned_passengers",
                "attendance_sessions",
                "qr_scanner",
                "attendance_history",
            ],
            "agency_admin": [
                "coordinator_management",
                "passenger_assignment",
                "session_monitoring",
                "attendance_history",
            ],
            "agency_staff": [
                "coordinator_management",
                "passenger_assignment",
                "session_monitoring",
                "attendance_history",
            ],
            "super_admin": [
                "all_agency_operations",
                "qr_revocation",
                "system_audit",
            ],
        },
        data_entities=[
            "coordinator_assignments",
            "passenger_qr_tokens",
            "attendance_sessions",
            "attendance_records",
        ],
        offline_strategy=[
            "Store pending scan events in IndexedDB on the coordinator PWA.",
            "Each scan carries a client_event_id for idempotent synchronization.",
            "Server prevents duplicate attendance through session/passenger uniqueness.",
            "UI must expose connectivity, pending sync count, and last sync time.",
        ],
        navigation=[
            "Dashboard sidebar entry for Tour Operations.",
            "Future mobile coordinator shell under a dedicated coordinator route.",
            "Future office views for sessions, progress, and missing passengers.",
        ],
        phases=[
            TourOperationsPhaseResponse(
                phase=1,
                name="Architecture and Planning",
                status="completed",
                scope=[
                    "permissions",
                    "QR security model",
                    "attendance entities",
                    "offline synchronization strategy",
                    "dashboard navigation",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=2,
                name="Scanner Proof of Concept",
                status="completed",
                scope=[
                    "camera permissions",
                    "continuous QR scanning",
                    "duplicate suppression",
                    "PWA install verification",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=3,
                name="Coordinator Module",
                status="completed",
                scope=[
                    "coordinator accounts",
                    "assigned groups",
                    "assigned passengers",
                    "even passenger distribution",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=4,
                name="Coordinator PWA Shell",
                status="completed",
                scope=[
                    "coordinator login shell",
                    "assigned groups",
                    "assigned passengers",
                    "mobile scanner entry point",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=5,
                name="Activity Attendance",
                status="completed",
                scope=[
                    "named attendance activities",
                    "group-specific scanner",
                    "idempotent QR scan counting",
                    "office attendance progress view",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=6,
                name="Offline Fast Scanner",
                status="completed",
                scope=[
                    "IndexedDB scan queue",
                    "offline snapshot storage",
                    "sub-second duplicate suppression",
                    "PWA route caching",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=7,
                name="QR Distribution",
                status="completed",
                scope=[
                    "office QR payload endpoint",
                    "printable passenger QR cards",
                    "manager-scoped group access",
                    "dashboard QR navigation",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=8,
                name="Speed, Security, and WhatsApp Foundation",
                status="completed",
                scope=[
                    "strict QR payload validation",
                    "race-safe scan inserts",
                    "offline duplicate suppression",
                    "disconnected WhatsApp broadcast planner",
                    "dry-run WhatsApp provider contract",
                ],
            ),
        ],
    )


@router.get(
    "/coordinators",
    response_model=list[CoordinatorResponse],
    status_code=status.HTTP_200_OK,
    summary="List coordinator accounts",
)
async def list_coordinators(
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[CoordinatorResponse]:
    agency_id = _require_agency(current_user)
    result = await session.execute(
        select(UserModel)
        .where(
            UserModel.agency_id == agency_id,
            UserModel.role == UserRole.AGENCY_COORDINATOR.value,
        )
        .order_by(UserModel.created_at.desc())
    )
    coordinators = list(result.scalars().all())
    return await _coordinator_responses(session, coordinators)


@router.post(
    "/coordinators",
    response_model=CoordinatorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a coordinator account",
)
async def create_coordinator(
    body: CreateCoordinatorRequest,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> CoordinatorResponse:
    agency_id = _require_agency(current_user)
    email = str(body.email).lower().strip()
    existing = await session.execute(select(UserModel).where(UserModel.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    coordinator = UserModel(
        email=email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name.strip(),
        role=UserRole.AGENCY_COORDINATOR.value,
        agency_id=agency_id,
        is_active=True,
    )
    session.add(coordinator)
    await session.flush()
    return (await _coordinator_responses(session, [coordinator]))[0]


@router.get(
    "/groups",
    response_model=list[TourOperationsGroupResponse],
    status_code=status.HTTP_200_OK,
    summary="List tour operation groups with coordinator coverage",
)
async def list_tour_operation_groups(
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[TourOperationsGroupResponse]:
    agency_id = _require_agency(current_user)
    filters = [
        ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.status != "deleted",
    ]
    if current_user.role == UserRole.AGENCY_STAFF:
        filters.append(_manager_group_visibility_filter(current_user))

    groups_result = await session.execute(
        select(ClientGroupModel)
        .where(*filters)
        .order_by(ClientGroupModel.created_at.desc())
    )
    return await _group_responses(session, list(groups_result.scalars().all()))


@router.put(
    "/groups/{group_id}/coordinators",
    response_model=TourOperationsGroupResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign multiple coordinators and evenly divide group passengers",
)
async def assign_group_coordinators(
    group_id: uuid.UUID,
    body: AssignGroupCoordinatorsRequest,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> TourOperationsGroupResponse:
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(session, agency_id, group_id, current_user)
    coordinator_ids = list(dict.fromkeys(body.coordinator_ids))

    if coordinator_ids:
        coordinator_result = await session.execute(
            select(UserModel.id)
            .where(
                UserModel.id.in_(coordinator_ids),
                UserModel.agency_id == agency_id,
                UserModel.role == UserRole.AGENCY_COORDINATOR.value,
                UserModel.is_active.is_(True),
            )
        )
        valid_ids = set(coordinator_result.scalars().all())
        if valid_ids != set(coordinator_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more coordinators are not assignable")

    now = datetime.now(tz=timezone.utc)
    await session.execute(
        update(CoordinatorGroupAssignmentModel)
        .where(
            CoordinatorGroupAssignmentModel.agency_id == agency_id,
            CoordinatorGroupAssignmentModel.group_id == group_id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
        .values(active=False, unassigned_at=now)
    )

    if coordinator_ids:
        for coordinator_id in coordinator_ids:
            session.add(
                CoordinatorGroupAssignmentModel(
                    agency_id=agency_id,
                    group_id=group_id,
                    coordinator_user_id=coordinator_id,
                    assigned_by_user_id=current_user.id,
                    active=True,
                    assigned_at=now,
                )
            )

        await session.execute(
            update(CoordinatorAssignmentModel)
            .where(
                CoordinatorAssignmentModel.agency_id == agency_id,
                CoordinatorAssignmentModel.group_id == group_id,
                CoordinatorAssignmentModel.active.is_(True),
                CoordinatorAssignmentModel.coordinator_user_id.notin_(coordinator_ids),
            )
            .values(active=False, unassigned_at=now)
        )
    else:
        await session.execute(
            update(CoordinatorAssignmentModel)
            .where(
                CoordinatorAssignmentModel.agency_id == agency_id,
                CoordinatorAssignmentModel.group_id == group_id,
                CoordinatorAssignmentModel.active.is_(True),
            )
            .values(active=False, unassigned_at=now)
        )

    await session.flush()
    return (await _group_responses(session, [group]))[0]


@router.get(
    "/groups/{group_id}/passengers",
    response_model=list[AssignedPassengerResponse],
    status_code=status.HTTP_200_OK,
    summary="List submitted passengers in a tour group with coordinator assignment",
)
async def list_group_passengers(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[AssignedPassengerResponse]:
    agency_id = _require_agency(current_user)
    await _get_manageable_group(session, agency_id, group_id, current_user)
    return await _group_passenger_responses(session, agency_id, group_id)


@router.get(
    "/groups/{group_id}/qr-codes",
    response_model=GroupPassengerQrCodesResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate printable QR payloads for submitted passengers in an office-managed group",
)
async def get_group_passenger_qr_codes(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GroupPassengerQrCodesResponse:
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(session, agency_id, group_id, current_user)
    return await _group_passenger_qr_codes(session, agency_id, group, current_user.id)


@router.put(
    "/groups/{group_id}/passengers/assign",
    response_model=list[AssignedPassengerResponse],
    status_code=status.HTTP_200_OK,
    summary="Assign selected group passengers to one assigned coordinator",
)
async def assign_group_passengers(
    group_id: uuid.UUID,
    body: AssignGroupPassengersRequest,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[AssignedPassengerResponse]:
    agency_id = _require_agency(current_user)
    await _get_manageable_group(session, agency_id, group_id, current_user)
    passenger_ids = list(dict.fromkeys(body.passenger_ids))

    passenger_result = await session.execute(
        select(PassportSubmissionModel.id)
        .where(
            PassportSubmissionModel.id.in_(passenger_ids),
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
        )
    )
    valid_passenger_ids = set(passenger_result.scalars().all())
    if valid_passenger_ids != set(passenger_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more passengers are not assignable")

    if body.coordinator_id is not None:
        coordinator_result = await session.execute(
            select(CoordinatorGroupAssignmentModel.id)
            .where(
                CoordinatorGroupAssignmentModel.agency_id == agency_id,
                CoordinatorGroupAssignmentModel.group_id == group_id,
                CoordinatorGroupAssignmentModel.coordinator_user_id == body.coordinator_id,
                CoordinatorGroupAssignmentModel.active.is_(True),
            )
        )
        if not coordinator_result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Coordinator is not assigned to this group")

    now = datetime.now(tz=timezone.utc)
    await session.execute(
        update(CoordinatorAssignmentModel)
        .where(
            CoordinatorAssignmentModel.agency_id == agency_id,
            CoordinatorAssignmentModel.group_id == group_id,
            CoordinatorAssignmentModel.passenger_id.in_(passenger_ids),
            CoordinatorAssignmentModel.active.is_(True),
        )
        .values(active=False, unassigned_at=now)
    )

    if body.coordinator_id is not None:
        for passenger_id in passenger_ids:
            session.add(
                CoordinatorAssignmentModel(
                    agency_id=agency_id,
                    group_id=group_id,
                    passenger_id=passenger_id,
                    coordinator_user_id=body.coordinator_id,
                    assigned_by_user_id=current_user.id,
                    active=True,
                    assigned_at=now,
                )
            )

    await session.flush()
    return await _group_passenger_responses(session, agency_id, group_id)


@router.get(
    "/coordinator/groups",
    response_model=list[TourOperationsGroupResponse],
    status_code=status.HTTP_200_OK,
    summary="List groups assigned to the current coordinator",
)
async def list_my_coordinator_groups(
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> list[TourOperationsGroupResponse]:
    agency_id = _require_agency(current_user)
    group_ids_result = await session.execute(
        select(CoordinatorGroupAssignmentModel.group_id)
        .where(
            CoordinatorGroupAssignmentModel.agency_id == agency_id,
            CoordinatorGroupAssignmentModel.coordinator_user_id == current_user.id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
        .distinct()
    )
    group_ids = list(group_ids_result.scalars().all())
    if not group_ids:
        return []

    groups_result = await session.execute(
        select(ClientGroupModel)
        .where(ClientGroupModel.id.in_(group_ids), ClientGroupModel.agency_id == agency_id)
        .order_by(ClientGroupModel.created_at.desc())
    )
    return await _group_responses(session, list(groups_result.scalars().all()))


@router.get(
    "/coordinator/groups/{group_id}/passengers",
    response_model=list[AssignedPassengerResponse],
    status_code=status.HTTP_200_OK,
    summary="List passengers assigned to the current coordinator for a group",
)
async def list_my_group_passengers(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> list[AssignedPassengerResponse]:
    agency_id = _require_agency(current_user)
    await _get_group(session, agency_id, group_id)
    result = await session.execute(
        select(PassportSubmissionModel)
        .join(
            CoordinatorAssignmentModel,
            CoordinatorAssignmentModel.passenger_id == PassportSubmissionModel.id,
        )
        .where(
            CoordinatorAssignmentModel.agency_id == agency_id,
            CoordinatorAssignmentModel.group_id == group_id,
            CoordinatorAssignmentModel.coordinator_user_id == current_user.id,
            CoordinatorAssignmentModel.active.is_(True),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    return [
        AssignedPassengerResponse(
            id=passenger.id,
            client_name=passenger.client_name,
            client_email=passenger.client_email,
            client_phone=passenger.client_phone,
            status=passenger.status,
            coordinator_id=current_user.id,
            coordinator_name=current_user.full_name,
            qr_payload=await _ensure_passenger_qr_payload(session, agency_id, passenger.id, current_user.id),
        )
        for passenger in result.scalars().all()
    ]


@router.post(
    "/coordinator/groups/{group_id}/sessions",
    response_model=AttendanceSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a coordinator attendance activity for a group",
)
async def create_my_attendance_session(
    group_id: uuid.UUID,
    body: CreateAttendanceSessionRequest,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceSessionResponse:
    agency_id = _require_agency(current_user)
    await _ensure_group_assigned_to_coordinator(session, agency_id, group_id, current_user.id)
    now = datetime.now(tz=timezone.utc)
    attendance_session = AttendanceSessionModel(
        agency_id=agency_id,
        group_id=group_id,
        name=body.name.strip(),
        status="active",
        created_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
        started_at=now,
    )
    session.add(attendance_session)
    await session.flush()
    return await _attendance_session_response(session, attendance_session, current_user.id)


@router.get(
    "/coordinator/groups/{group_id}/sessions",
    response_model=list[AttendanceSessionResponse],
    status_code=status.HTTP_200_OK,
    summary="List current coordinator attendance activities for a group",
)
async def list_my_attendance_sessions(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> list[AttendanceSessionResponse]:
    agency_id = _require_agency(current_user)
    await _ensure_group_assigned_to_coordinator(session, agency_id, group_id, current_user.id)
    result = await session.execute(
        select(AttendanceSessionModel)
        .where(
            AttendanceSessionModel.agency_id == agency_id,
            AttendanceSessionModel.group_id == group_id,
            AttendanceSessionModel.created_by_user_id == current_user.id,
        )
        .order_by(AttendanceSessionModel.created_at.desc())
    )
    return [
        await _attendance_session_response(session, attendance_session, current_user.id)
        for attendance_session in result.scalars().all()
    ]


@router.post(
    "/coordinator/sessions/{session_id}/scan",
    response_model=AttendanceScanResponse,
    status_code=status.HTTP_200_OK,
    summary="Record one QR attendance scan for the current coordinator",
)
async def record_my_attendance_scan(
    session_id: uuid.UUID,
    body: AttendanceScanRequest,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceScanResponse:
    agency_id = _require_agency(current_user)
    attendance_session = await _get_coordinator_attendance_session(session, agency_id, session_id, current_user.id)
    if attendance_session.status not in ACTIVE_ATTENDANCE_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Attendance activity is not active")

    passenger = await _resolve_scannable_passenger(
        session=session,
        agency_id=agency_id,
        group_id=attendance_session.group_id,
        coordinator_id=current_user.id,
        qr_payload=body.qr_payload,
    )
    if not passenger:
        response = await _attendance_scan_response(
            session=session,
            attendance_session=attendance_session,
            coordinator_id=current_user.id,
            passenger_id=None,
            passenger_name=None,
            scan_status="invalid",
            message="QR code is not assigned to this coordinator and group.",
        )
        return response

    insert_result = await session.execute(
        pg_insert(AttendanceRecordModel)
        .values(
            agency_id=agency_id,
            session_id=session_id,
            passenger_id=passenger.id,
            coordinator_user_id=current_user.id,
            scanned_at=body.scanned_at or datetime.now(tz=timezone.utc),
            sync_source=body.sync_source,
            client_event_id=body.client_event_id,
            device_id=body.device_id,
        )
        .on_conflict_do_nothing()
        .returning(AttendanceRecordModel.id)
    )
    inserted_id = insert_result.scalar_one_or_none()
    if inserted_id is None:
        return await _attendance_scan_response(
            session=session,
            attendance_session=attendance_session,
            coordinator_id=current_user.id,
            passenger_id=passenger.id,
            passenger_name=passenger.client_name,
            scan_status="duplicate",
            message="This passenger is already counted for this activity.",
        )

    return await _attendance_scan_response(
        session=session,
        attendance_session=attendance_session,
        coordinator_id=current_user.id,
        passenger_id=passenger.id,
        passenger_name=passenger.client_name,
        scan_status="counted",
        message=f"{passenger.client_name} counted.",
    )


@router.put(
    "/coordinator/sessions/{session_id}/complete",
    response_model=AttendanceSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete the current coordinator attendance activity",
)
async def complete_my_attendance_session(
    session_id: uuid.UUID,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceSessionResponse:
    agency_id = _require_agency(current_user)
    attendance_session = await _get_coordinator_attendance_session(session, agency_id, session_id, current_user.id)
    now = datetime.now(tz=timezone.utc)
    attendance_session.status = "completed"
    attendance_session.completed_at = now
    attendance_session.updated_at = now
    await session.flush()
    return await _attendance_session_response(session, attendance_session, current_user.id)


@router.get(
    "/groups/{group_id}/attendance",
    response_model=GroupAttendanceOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get attendance activity progress for an office-managed group",
)
async def get_group_attendance_overview(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GroupAttendanceOverviewResponse:
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(session, agency_id, group_id, current_user)
    return await _group_attendance_overview(session, agency_id, group)


async def _get_group(session: AsyncSession, agency_id: uuid.UUID, group_id: uuid.UUID) -> ClientGroupModel:
    result = await session.execute(
        select(ClientGroupModel).where(ClientGroupModel.id == group_id, ClientGroupModel.agency_id == agency_id)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")
    return group


async def _get_manageable_group(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    current_user: User,
) -> ClientGroupModel:
    filters = [
        ClientGroupModel.id == group_id,
        ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.status != "deleted",
    ]
    if current_user.role == UserRole.AGENCY_STAFF:
        filters.append(_manager_group_visibility_filter(current_user))

    result = await session.execute(select(ClientGroupModel).where(*filters))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")
    return group


def _manager_group_visibility_filter(current_user: User):  # type: ignore[no-untyped-def]
    return (ClientGroupModel.created_by_user_id == current_user.id) | ClientGroupModel.id.in_(
        select(ManagerGroupAccessModel.group_id).where(ManagerGroupAccessModel.manager_id == current_user.id)
    )


async def _ensure_group_assigned_to_coordinator(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    coordinator_id: uuid.UUID,
) -> None:
    result = await session.execute(
        select(CoordinatorGroupAssignmentModel.id).where(
            CoordinatorGroupAssignmentModel.agency_id == agency_id,
            CoordinatorGroupAssignmentModel.group_id == group_id,
            CoordinatorGroupAssignmentModel.coordinator_user_id == coordinator_id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not assigned to this coordinator")


async def _get_coordinator_attendance_session(
    session: AsyncSession,
    agency_id: uuid.UUID,
    session_id: uuid.UUID,
    coordinator_id: uuid.UUID,
) -> AttendanceSessionModel:
    result = await session.execute(
        select(AttendanceSessionModel).where(
            AttendanceSessionModel.id == session_id,
            AttendanceSessionModel.agency_id == agency_id,
            AttendanceSessionModel.created_by_user_id == coordinator_id,
        )
    )
    attendance_session = result.scalar_one_or_none()
    if not attendance_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance activity was not found")
    return attendance_session


async def _attendance_session_response(
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
    coordinator_id: uuid.UUID,
) -> AttendanceSessionResponse:
    counts = await _attendance_counts(session, attendance_session.id, attendance_session.group_id, coordinator_id)
    return AttendanceSessionResponse(
        id=attendance_session.id,
        group_id=attendance_session.group_id,
        name=attendance_session.name,
        status=attendance_session.status,
        created_at=attendance_session.created_at,
        started_at=attendance_session.started_at,
        completed_at=attendance_session.completed_at,
        scanned_count=counts["scanned"],
        assigned_count=counts["assigned"],
    )


async def _attendance_scan_response(
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
    coordinator_id: uuid.UUID,
    passenger_id: uuid.UUID | None,
    passenger_name: str | None,
    scan_status: str,
    message: str,
) -> AttendanceScanResponse:
    counts = await _attendance_counts(session, attendance_session.id, attendance_session.group_id, coordinator_id)
    return AttendanceScanResponse(
        session_id=attendance_session.id,
        passenger_id=passenger_id,
        passenger_name=passenger_name,
        status=scan_status,
        message=message,
        scanned_count=counts["scanned"],
        assigned_count=counts["assigned"],
    )


async def _attendance_counts(
    session: AsyncSession,
    session_id: uuid.UUID,
    group_id: uuid.UUID,
    coordinator_id: uuid.UUID,
) -> dict[str, int]:
    assigned_result = await session.execute(
        select(func.count(CoordinatorAssignmentModel.passenger_id)).where(
            CoordinatorAssignmentModel.group_id == group_id,
            CoordinatorAssignmentModel.coordinator_user_id == coordinator_id,
            CoordinatorAssignmentModel.active.is_(True),
        )
    )
    scanned_result = await session.execute(
        select(func.count(AttendanceRecordModel.id)).where(
            AttendanceRecordModel.session_id == session_id,
            AttendanceRecordModel.coordinator_user_id == coordinator_id,
        )
    )
    return {
        "assigned": int(assigned_result.scalar_one() or 0),
        "scanned": int(scanned_result.scalar_one() or 0),
    }


async def _ensure_passenger_qr_payload(
    session: AsyncSession,
    agency_id: uuid.UUID,
    passenger_id: uuid.UUID,
    created_by_user_id: uuid.UUID | None,
) -> str:
    payload = _qr_payload(agency_id, passenger_id)
    token_hash = _qr_hash(payload)
    result = await session.execute(
        select(PassengerQRTokenModel.id).where(
            PassengerQRTokenModel.passenger_id == passenger_id,
            PassengerQRTokenModel.token_hash == token_hash,
            PassengerQRTokenModel.is_active.is_(True),
        )
    )
    if not result.scalar_one_or_none():
        session.add(
            PassengerQRTokenModel(
                agency_id=agency_id,
                passenger_id=passenger_id,
                token_hash=token_hash,
                token_version=1,
                is_active=True,
                created_by_user_id=created_by_user_id,
                created_at=datetime.now(tz=timezone.utc),
                updated_at=datetime.now(tz=timezone.utc),
            )
        )
        await session.flush()
    return payload


async def _resolve_scannable_passenger(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    coordinator_id: uuid.UUID,
    qr_payload: str,
) -> PassportSubmissionModel | None:
    token_hash = _qr_hash(qr_payload.strip())
    result = await session.execute(
        select(PassportSubmissionModel)
        .join(PassengerQRTokenModel, PassengerQRTokenModel.passenger_id == PassportSubmissionModel.id)
        .join(CoordinatorAssignmentModel, CoordinatorAssignmentModel.passenger_id == PassportSubmissionModel.id)
        .where(
            PassengerQRTokenModel.agency_id == agency_id,
            PassengerQRTokenModel.token_hash == token_hash,
            PassengerQRTokenModel.is_active.is_(True),
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            CoordinatorAssignmentModel.agency_id == agency_id,
            CoordinatorAssignmentModel.group_id == group_id,
            CoordinatorAssignmentModel.coordinator_user_id == coordinator_id,
            CoordinatorAssignmentModel.active.is_(True),
        )
    )
    return result.scalars().first()


async def _group_attendance_overview(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group: ClientGroupModel,
) -> GroupAttendanceOverviewResponse:
    sessions_result = await session.execute(
        select(AttendanceSessionModel)
        .where(
            AttendanceSessionModel.agency_id == agency_id,
            AttendanceSessionModel.group_id == group.id,
        )
        .order_by(AttendanceSessionModel.created_at.desc())
    )
    attendance_sessions = list(sessions_result.scalars().all())
    if not attendance_sessions:
        return GroupAttendanceOverviewResponse(group_id=group.id, group_name=group.name, sessions=[])

    session_ids = [attendance_session.id for attendance_session in attendance_sessions]
    assigned_result = await session.execute(
        select(
            CoordinatorAssignmentModel.coordinator_user_id,
            UserModel.full_name,
            func.count(CoordinatorAssignmentModel.passenger_id).label("assigned_count"),
        )
        .join(UserModel, UserModel.id == CoordinatorAssignmentModel.coordinator_user_id)
        .where(
            CoordinatorAssignmentModel.agency_id == agency_id,
            CoordinatorAssignmentModel.group_id == group.id,
            CoordinatorAssignmentModel.active.is_(True),
        )
        .group_by(CoordinatorAssignmentModel.coordinator_user_id, UserModel.full_name)
    )
    assigned_by_coordinator = {
        row.coordinator_user_id: (row.full_name, int(row.assigned_count))
        for row in assigned_result.all()
    }

    scanned_result = await session.execute(
        select(
            AttendanceRecordModel.session_id,
            AttendanceRecordModel.coordinator_user_id,
            func.count(AttendanceRecordModel.passenger_id).label("scanned_count"),
        )
        .where(AttendanceRecordModel.session_id.in_(session_ids))
        .group_by(AttendanceRecordModel.session_id, AttendanceRecordModel.coordinator_user_id)
    )
    scanned_counts = {
        (row.session_id, row.coordinator_user_id): int(row.scanned_count)
        for row in scanned_result.all()
    }

    assigned_passengers_result = await session.execute(
        select(
            CoordinatorAssignmentModel.passenger_id,
            CoordinatorAssignmentModel.coordinator_user_id,
            UserModel.full_name.label("coordinator_name"),
            PassportSubmissionModel.client_name,
            PassportSubmissionModel.client_email,
            PassportSubmissionModel.client_phone,
        )
        .join(UserModel, UserModel.id == CoordinatorAssignmentModel.coordinator_user_id)
        .join(PassportSubmissionModel, PassportSubmissionModel.id == CoordinatorAssignmentModel.passenger_id)
        .where(
            CoordinatorAssignmentModel.agency_id == agency_id,
            CoordinatorAssignmentModel.group_id == group.id,
            CoordinatorAssignmentModel.active.is_(True),
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
        )
        .order_by(UserModel.full_name.asc(), PassportSubmissionModel.client_name.asc())
    )
    assigned_passengers = list(assigned_passengers_result.all())

    scanned_passengers_result = await session.execute(
        select(AttendanceRecordModel.session_id, AttendanceRecordModel.passenger_id)
        .where(AttendanceRecordModel.session_id.in_(session_ids))
    )
    scanned_passenger_ids = defaultdict(set)
    for row in scanned_passengers_result.all():
        scanned_passenger_ids[row.session_id].add(row.passenger_id)

    summaries: list[AttendanceSessionSummary] = []
    for attendance_session in attendance_sessions:
        coordinators = [
            AttendanceCoordinatorSummary(
                coordinator_id=coordinator_id,
                coordinator_name=name,
                assigned_count=assigned_count,
                scanned_count=scanned_counts.get((attendance_session.id, coordinator_id), 0),
            )
            for coordinator_id, (name, assigned_count) in assigned_by_coordinator.items()
        ]
        missing_passengers = [
            AttendanceMissingPassenger(
                passenger_id=row.passenger_id,
                client_name=row.client_name,
                client_email=row.client_email,
                client_phone=row.client_phone,
                coordinator_id=row.coordinator_user_id,
                coordinator_name=row.coordinator_name,
            )
            for row in assigned_passengers
            if row.passenger_id not in scanned_passenger_ids[attendance_session.id]
        ]
        summaries.append(
            AttendanceSessionSummary(
                id=attendance_session.id,
                name=attendance_session.name,
                status=attendance_session.status,
                created_at=attendance_session.created_at,
                started_at=attendance_session.started_at,
                completed_at=attendance_session.completed_at,
                assigned_count=sum(item.assigned_count for item in coordinators),
                scanned_count=sum(item.scanned_count for item in coordinators),
                coordinators=coordinators,
                missing_passengers=missing_passengers,
            )
        )

    return GroupAttendanceOverviewResponse(group_id=group.id, group_name=group.name, sessions=summaries)


async def _group_passenger_qr_codes(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group: ClientGroupModel,
    created_by_user_id: uuid.UUID,
) -> GroupPassengerQrCodesResponse:
    assignment_subquery = (
        select(
            CoordinatorAssignmentModel.passenger_id.label("passenger_id"),
            CoordinatorAssignmentModel.coordinator_user_id.label("coordinator_id"),
        )
        .where(
            CoordinatorAssignmentModel.agency_id == agency_id,
            CoordinatorAssignmentModel.group_id == group.id,
            CoordinatorAssignmentModel.active.is_(True),
        )
        .subquery()
    )
    result = await session.execute(
        select(
            PassportSubmissionModel,
            UserModel.id.label("coordinator_id"),
            UserModel.full_name.label("coordinator_name"),
        )
        .outerjoin(assignment_subquery, assignment_subquery.c.passenger_id == PassportSubmissionModel.id)
        .outerjoin(UserModel, UserModel.id == assignment_subquery.c.coordinator_id)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )

    passengers: list[GroupPassengerQrCodeResponse] = []
    for passenger, coordinator_id, coordinator_name in result.all():
        passengers.append(
            GroupPassengerQrCodeResponse(
                passenger_id=passenger.id,
                client_name=passenger.client_name,
                client_email=passenger.client_email,
                client_phone=passenger.client_phone,
                coordinator_id=coordinator_id,
                coordinator_name=coordinator_name,
                qr_payload=await _ensure_passenger_qr_payload(session, agency_id, passenger.id, created_by_user_id),
            )
        )

    return GroupPassengerQrCodesResponse(
        group_id=group.id,
        group_name=group.name,
        generated_at=datetime.now(tz=timezone.utc),
        passengers=passengers,
    )


def _qr_payload(agency_id: uuid.UUID, passenger_id: uuid.UUID) -> str:
    token = uuid.uuid5(uuid.NAMESPACE_URL, f"passdetection:attendance:{agency_id}:{passenger_id}:v1")
    return f"pdatt:{token}"


def _qr_hash(payload: str) -> str:
    return sha256(payload.encode("utf-8")).hexdigest()


async def _coordinator_responses(session: AsyncSession, coordinators: list[UserModel]) -> list[CoordinatorResponse]:
    if not coordinators:
        return []
    coordinator_ids = [coordinator.id for coordinator in coordinators]
    group_counts_result = await session.execute(
        select(
            CoordinatorGroupAssignmentModel.coordinator_user_id,
            func.count(func.distinct(CoordinatorGroupAssignmentModel.group_id)).label("group_count"),
        )
        .where(
            CoordinatorGroupAssignmentModel.coordinator_user_id.in_(coordinator_ids),
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
        .group_by(CoordinatorGroupAssignmentModel.coordinator_user_id)
    )
    group_counts = {row.coordinator_user_id: int(row.group_count) for row in group_counts_result.all()}

    passenger_counts_result = await session.execute(
        select(
            CoordinatorAssignmentModel.coordinator_user_id,
            func.count(CoordinatorAssignmentModel.passenger_id).label("passenger_count"),
        )
        .where(
            CoordinatorAssignmentModel.coordinator_user_id.in_(coordinator_ids),
            CoordinatorAssignmentModel.active.is_(True),
        )
        .group_by(CoordinatorAssignmentModel.coordinator_user_id)
    )
    passenger_counts = {row.coordinator_user_id: int(row.passenger_count) for row in passenger_counts_result.all()}
    return [
        CoordinatorResponse(
            id=coordinator.id,
            full_name=coordinator.full_name,
            email=coordinator.email,
            agency_id=coordinator.agency_id,
            is_active=coordinator.is_active,
            created_at=coordinator.created_at,
            last_login_at=coordinator.last_login_at,
            assigned_groups_count=group_counts.get(coordinator.id, 0),
            assigned_passengers_count=passenger_counts.get(coordinator.id, 0),
        )
        for coordinator in coordinators
        if coordinator.agency_id is not None
    ]


async def _group_responses(session: AsyncSession, groups: list[ClientGroupModel]) -> list[TourOperationsGroupResponse]:
    if not groups:
        return []
    group_ids = [group.id for group in groups]

    passenger_counts_result = await session.execute(
        select(PassportSubmissionModel.group_id, func.count(PassportSubmissionModel.id))
        .where(
            PassportSubmissionModel.group_id.in_(group_ids),
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
        )
        .group_by(PassportSubmissionModel.group_id)
    )
    passenger_counts = {group_id: int(count) for group_id, count in passenger_counts_result.all()}

    group_coordinators_result = await session.execute(
        select(
            CoordinatorGroupAssignmentModel.group_id,
            UserModel.id,
            UserModel.full_name,
            UserModel.email,
        )
        .join(UserModel, UserModel.id == CoordinatorGroupAssignmentModel.coordinator_user_id)
        .where(
            CoordinatorGroupAssignmentModel.group_id.in_(group_ids),
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
        .order_by(UserModel.full_name.asc())
    )

    assigned_counts_result = await session.execute(
        select(
            CoordinatorAssignmentModel.group_id,
            CoordinatorAssignmentModel.coordinator_user_id,
            func.count(CoordinatorAssignmentModel.passenger_id).label("passenger_count"),
        )
        .where(
            CoordinatorAssignmentModel.group_id.in_(group_ids),
            CoordinatorAssignmentModel.active.is_(True),
        )
        .group_by(CoordinatorAssignmentModel.group_id, CoordinatorAssignmentModel.coordinator_user_id)
    )
    coordinator_passenger_counts = {
        (row.group_id, row.coordinator_user_id): int(row.passenger_count)
        for row in assigned_counts_result.all()
    }
    assignments: dict[uuid.UUID, list[GroupCoordinatorAssignmentResponse]] = defaultdict(list)
    assigned_counts: dict[uuid.UUID, int] = defaultdict(int)
    for row in group_coordinators_result.all():
        count = coordinator_passenger_counts.get((row.group_id, row.id), 0)
        assignments[row.group_id].append(
            GroupCoordinatorAssignmentResponse(
                coordinator_id=row.id,
                full_name=row.full_name,
                email=row.email,
                assigned_passengers_count=count,
            )
        )

    for (group_id, _coordinator_id), count in coordinator_passenger_counts.items():
        assigned_counts[group_id] += count

    return [
        TourOperationsGroupResponse(
            id=group.id,
            name=group.name,
            status=group.status,
            destination=group.destination,
            travel_date=group.travel_date.isoformat() if group.travel_date else None,
            passenger_count=passenger_counts.get(group.id, 0),
            assigned_passengers_count=assigned_counts.get(group.id, 0),
            unassigned_passengers_count=max(0, passenger_counts.get(group.id, 0) - assigned_counts.get(group.id, 0)),
            coordinators=assignments[group.id],
        )
        for group in groups
    ]


async def _group_passenger_responses(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> list[AssignedPassengerResponse]:
    assignment_subquery = (
        select(
            CoordinatorAssignmentModel.passenger_id.label("passenger_id"),
            CoordinatorAssignmentModel.coordinator_user_id.label("coordinator_id"),
        )
        .where(
            CoordinatorAssignmentModel.agency_id == agency_id,
            CoordinatorAssignmentModel.group_id == group_id,
            CoordinatorAssignmentModel.active.is_(True),
        )
        .subquery()
    )
    result = await session.execute(
        select(
            PassportSubmissionModel,
            UserModel.id.label("coordinator_id"),
            UserModel.full_name.label("coordinator_name"),
        )
        .outerjoin(assignment_subquery, assignment_subquery.c.passenger_id == PassportSubmissionModel.id)
        .outerjoin(UserModel, UserModel.id == assignment_subquery.c.coordinator_id)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    return [
        AssignedPassengerResponse(
            id=passenger.id,
            client_name=passenger.client_name,
            client_email=passenger.client_email,
            client_phone=passenger.client_phone,
            status=passenger.status,
            coordinator_id=coordinator_id,
            coordinator_name=coordinator_name,
        )
        for passenger, coordinator_id, coordinator_name in result.all()
    ]
