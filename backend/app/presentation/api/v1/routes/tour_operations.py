"""
Tour Operations Routes
======================
Coordinator account and group-assignment operations.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.application.mobile.sync_journal import (
    append_attendance_realtime_invalidation,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.attendance_dashboard import (
    AttendanceActivityNotFoundError,
    AttendanceDashboardService,
    AttendanceSnapshotChangedError,
)
from app.core.config.settings import get_settings
from app.core.security.password import hash_password
from app.domain.entities.entities import GroupStatus, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError, StepUpRequiredError
from app.domain.value_objects.attendance_activity import (
    normalize_attendance_activity_name,
)
from app.infrastructure.database.models import (
    AttendanceRecordModel,
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutRepository,
)
from app.infrastructure.repositories.attendance_dashboard_repository import (
    AttendanceDashboardRepository,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.presentation.api.v1.routes.tour_operations_attendance_batch_support import (
    AttendanceBatchDependencies,
    process_coordinator_attendance_scan_batch,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    attendance_activity_valid_after as _attendance_activity_valid_after,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    attendance_closeout_audit_metadata as _attendance_closeout_audit_metadata,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    attendance_closeout_counts as _attendance_closeout_counts,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    attendance_closeout_status_response as _attendance_closeout_status_response,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    attendance_missing_passengers_response,
    attendance_snapshot_changed_response,
    attendance_summary_cache_headers,
    attendance_summary_response,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    close_shared_attendance_activity as _close_shared_attendance_activity,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    etag_matches as _etag_matches,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    require_attendance_closeout_clearance as _require_attendance_closeout_clearance,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    SCANNABLE_ATTENDANCE_STATUSES as SCANNABLE_ATTENDANCE_STATUSES,  # noqa: F401 - compatibility re-export
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    SUBMITTED_PASSENGER_STATUSES,
    TourAttendanceScanDependencies,
    record_coordinator_attendance_scan,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    attendance_scan_is_within_activity_window as _attendance_scan_is_within_activity_window,  # noqa: F401 - compatibility re-export
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    counted_attendance_message as _counted_attendance_message,  # noqa: F401 - compatibility re-export
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    insert_canonical_attendance_record as _insert_canonical_attendance_record,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    resolve_scannable_passenger as _resolve_scannable_passenger,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    get_qr_passenger as _get_qr_passenger,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    group_passenger_qr_codes as _group_passenger_qr_codes,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    issue_passenger_qr as _issue_passenger_qr,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    latest_passenger_qr as _latest_passenger_qr,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    qr_hash,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    qr_payload as _qr_payload,  # noqa: F401 - compatibility re-export
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    qr_status as _qr_status,  # noqa: F401 - compatibility re-export
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    qr_token_response as _qr_token_response,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    record_qr_audit as _record_qr_audit,
)
from app.presentation.api.v1.routes.tour_operations_response_support import (
    coordinator_responses as _coordinator_responses,
)
from app.presentation.api.v1.routes.tour_operations_response_support import (
    group_responses as _group_responses,
)
from app.presentation.api.v1.schemas.attendance_closeout_schemas import (
    AttendanceCloseoutCheckpointRequest,
    AttendanceCloseoutCheckpointResponse,
    AttendanceCloseoutStatusResponse,
    AttendanceCloseRequest,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AssignedPassengerDetailResponse,
    AssignedPassengerResponse,
    AssignGroupCoordinatorsRequest,
    AssignGroupPassengersRequest,
    AttendanceCoordinatorSummary,
    AttendanceMissingPassenger,
    AttendanceMissingPassengersPageResponse,
    AttendancePassengerStatus,
    AttendanceScanBatchRequest,
    AttendanceScanBatchResponse,
    AttendanceScanRequest,
    AttendanceScanResponse,
    AttendanceSessionDetailsResponse,
    AttendanceSessionResponse,
    AttendanceSessionSummary,
    CoordinatorResponse,
    CreateAttendanceSessionRequest,
    CreateCoordinatorRequest,
    GroupAttendanceOverviewResponse,
    GroupAttendanceSummaryResponse,
    GroupPassengerQrCodesResponse,
    PassengerQrTokenResponse,
    SetPassengerQrActiveRequest,
    SetPassengerQrExpirationRequest,
    TourOperationsArchitectureResponse,
    TourOperationsGroupResponse,
    TourOperationsPhaseResponse,
    UpdateAttendanceScheduleRequest,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.attendance_runtime import (
    resolve_browser_attendance_runtime,
)
from app.presentation.security.client_ip import trusted_client_ip

_qr_hash = qr_hash

router = APIRouter()

TOUR_OPERATION_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
    UserRole.AGENCY_COORDINATOR,
]
COORDINATOR_MANAGEMENT_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]
COORDINATOR_ACCOUNT_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
]
ATTENDANCE_CLOSURE_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
]
TOUR_OPERATION_GROUP_STATUSES = (
    GroupStatus.ACTIVE.value,
    GroupStatus.CLOSED.value,
)


def _require_agency(current_user: User) -> uuid.UUID:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User is not assigned to an agency"
        )
    return current_user.agency_id


def _agency_scope(current_user: User) -> uuid.UUID | None:
    """Return the agency scope for office list views.

    Super admins are intentionally allowed to have no agency. They should still
    be able to open empty/new production dashboards without every agency-scoped
    overview endpoint failing with 400.
    """
    if current_user.role == UserRole.SUPER_ADMIN:
        return current_user.agency_id
    return _require_agency(current_user)


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
            "agency_manager": [
                "coordinator_management",
                "passenger_assignment",
                "session_monitoring",
                "attendance_history",
            ],
            "agency_staff": [
                "assigned_groups",
                "rooming_lists",
                "document_distribution",
                "document_rename_own_batches",
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
    agency_id = _agency_scope(current_user)
    filters: list[ColumnElement[bool]] = [
        UserModel.role == UserRole.AGENCY_COORDINATOR.value,
        UserModel.deleted_at.is_(None),
    ]
    if agency_id is not None:
        filters.append(UserModel.agency_id == agency_id)
    result = await session.execute(
        select(UserModel).where(*filters).order_by(UserModel.created_at.desc())
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
    request: Request,
    current_user: User = Depends(require_role(COORDINATOR_ACCOUNT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> CoordinatorResponse:
    agency_id = _require_agency(current_user)
    email = str(body.email).lower().strip()
    existing = await session.execute(select(UserModel).where(UserModel.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists"
        )

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
    await AuditLogRepository(session).record(
        action="account.created",
        entity_type="user_account",
        agency_id=coordinator.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(coordinator.id),
        ip_address=trusted_client_ip(request),
        metadata={"target_role": coordinator.role, "target_email": coordinator.email},
    )
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
    agency_id = _agency_scope(current_user)
    filters: list[ColumnElement[bool]] = [
        ClientGroupModel.status.in_(TOUR_OPERATION_GROUP_STATUSES),
    ]
    if agency_id is not None:
        filters.append(ClientGroupModel.agency_id == agency_id)

    stmt = AuthorizationPolicy.apply_group_visibility_scope(
        select(ClientGroupModel).where(*filters), current_user
    )
    groups_result = await session.execute(stmt.order_by(ClientGroupModel.created_at.desc()))
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
    group = await _get_manageable_group(
        session,
        agency_id,
        group_id,
        current_user,
        lock_for_update=True,
    )
    coordinator_ids = list(dict.fromkeys(body.coordinator_ids))

    if coordinator_ids:
        coordinator_result = await session.execute(
            select(UserModel.id).where(
                UserModel.id.in_(coordinator_ids),
                UserModel.agency_id == agency_id,
                UserModel.role == UserRole.AGENCY_COORDINATOR.value,
                UserModel.is_active.is_(True),
            )
        )
        valid_ids = set(coordinator_result.scalars().all())
        if valid_ids != set(coordinator_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more coordinators are not assignable",
            )

    now = datetime.now(tz=UTC)
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
    summary="List QR lifecycle status for submitted passengers in an office-managed group",
)
async def get_group_passenger_qr_codes(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GroupPassengerQrCodesResponse:
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(session, agency_id, group_id, current_user)
    return await _group_passenger_qr_codes(session, agency_id, group)


@router.post(
    "/groups/{group_id}/passengers/{passenger_id}/qr",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=PassengerQrTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a secure attendance QR token and reveal it once",
)
async def generate_passenger_qr(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> PassengerQrTokenResponse:
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(session, agency_id, group_id, current_user)
    await _get_qr_passenger(session, agency_id, group_id, passenger_id)
    token, payload = await _issue_passenger_qr(
        session, agency_id, passenger_id, current_user.id, group=group, regenerate=False
    )
    await _record_qr_audit(
        session,
        current_user,
        request,
        action="qr.generated",
        passenger_id=passenger_id,
        metadata={"group_id": str(group_id), "token_version": token.token_version},
    )
    return _qr_token_response(token, payload)


@router.post(
    "/groups/{group_id}/passengers/{passenger_id}/qr/regenerate",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=PassengerQrTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke the current attendance QR and reveal a random replacement once",
)
async def regenerate_passenger_qr(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> PassengerQrTokenResponse:
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(session, agency_id, group_id, current_user)
    await _get_qr_passenger(session, agency_id, group_id, passenger_id)
    token, payload = await _issue_passenger_qr(
        session, agency_id, passenger_id, current_user.id, group=group, regenerate=True
    )
    await _record_qr_audit(
        session,
        current_user,
        request,
        action="qr.regenerated",
        passenger_id=passenger_id,
        metadata={"group_id": str(group_id), "token_version": token.token_version},
    )
    return _qr_token_response(token, payload)


@router.post(
    "/groups/{group_id}/passengers/{passenger_id}/qr/revoke",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=PassengerQrTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Permanently revoke a passenger attendance QR",
)
async def revoke_passenger_qr(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> PassengerQrTokenResponse:
    agency_id = _require_agency(current_user)
    await _get_manageable_group(session, agency_id, group_id, current_user)
    await _get_qr_passenger(session, agency_id, group_id, passenger_id)
    token = await _latest_passenger_qr(session, passenger_id, lock=True)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passenger has no QR token"
        )
    if token.revoked_at is None:
        now = datetime.now(tz=UTC)
        token.is_active = False
        token.revoked_at = now
        token.updated_at = now
        await session.flush()
    await _record_qr_audit(
        session,
        current_user,
        request,
        action="qr.revoked",
        passenger_id=passenger_id,
        metadata={"group_id": str(group_id), "token_version": token.token_version},
    )
    return _qr_token_response(token)


@router.patch(
    "/groups/{group_id}/passengers/{passenger_id}/qr/active",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=PassengerQrTokenResponse,
    summary="Mark the latest passenger QR active or inactive",
)
async def set_passenger_qr_active(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    body: SetPassengerQrActiveRequest,
    request: Request,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> PassengerQrTokenResponse:
    agency_id = _require_agency(current_user)
    await _get_manageable_group(session, agency_id, group_id, current_user)
    await _get_qr_passenger(session, agency_id, group_id, passenger_id)
    token = await _latest_passenger_qr(session, passenger_id, lock=True)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passenger has no QR token"
        )
    now = datetime.now(tz=UTC)
    if body.is_active and (token.revoked_at is not None or token.expires_at <= now):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Revoked or expired QR tokens cannot be activated; regenerate the QR instead",
        )
    if body.is_active:
        await session.execute(
            update(PassengerQRTokenModel)
            .where(
                PassengerQRTokenModel.passenger_id == passenger_id,
                PassengerQRTokenModel.id != token.id,
                PassengerQRTokenModel.is_active.is_(True),
            )
            .values(is_active=False, updated_at=now)
        )
    token.is_active = body.is_active
    token.updated_at = now
    await session.flush()
    await _record_qr_audit(
        session,
        current_user,
        request,
        action="qr.activated" if body.is_active else "qr.deactivated",
        passenger_id=passenger_id,
        metadata={"group_id": str(group_id), "token_version": token.token_version},
    )
    return _qr_token_response(token)


@router.patch(
    "/groups/{group_id}/passengers/{passenger_id}/qr/expiration",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=PassengerQrTokenResponse,
    summary="Change or immediately expire the latest passenger QR",
)
async def set_passenger_qr_expiration(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    body: SetPassengerQrExpirationRequest,
    request: Request,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> PassengerQrTokenResponse:
    agency_id = _require_agency(current_user)
    await _get_manageable_group(session, agency_id, group_id, current_user)
    await _get_qr_passenger(session, agency_id, group_id, passenger_id)
    token = await _latest_passenger_qr(session, passenger_id, lock=True)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passenger has no QR token"
        )
    if token.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Revoked QR tokens cannot be changed"
        )
    expires_at = body.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    now = datetime.now(tz=UTC)
    token.expires_at = expires_at
    if expires_at <= now:
        token.is_active = False
    token.updated_at = now
    await session.flush()
    await _record_qr_audit(
        session,
        current_user,
        request,
        action="qr.expired" if expires_at <= now else "qr.expiration_changed",
        passenger_id=passenger_id,
        metadata={
            "group_id": str(group_id),
            "token_version": token.token_version,
            "expires_at": expires_at.isoformat(),
        },
    )
    return _qr_token_response(token)


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
    # Compatibility-only endpoint retained for rollback. The dashboard no
    # longer calls it, and attendance authorization ignores these assignments.
    agency_id = _require_agency(current_user)
    await _get_manageable_group(session, agency_id, group_id, current_user)
    passenger_ids = list(dict.fromkeys(body.passenger_ids))

    passenger_result = await session.execute(
        select(PassportSubmissionModel.id).where(
            PassportSubmissionModel.id.in_(passenger_ids),
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
    )
    valid_passenger_ids = set(passenger_result.scalars().all())
    if valid_passenger_ids != set(passenger_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more passengers are not assignable",
        )

    if body.coordinator_id is not None:
        coordinator_result = await session.execute(
            select(CoordinatorGroupAssignmentModel.id).where(
                CoordinatorGroupAssignmentModel.agency_id == agency_id,
                CoordinatorGroupAssignmentModel.group_id == group_id,
                CoordinatorGroupAssignmentModel.coordinator_user_id == body.coordinator_id,
                CoordinatorGroupAssignmentModel.active.is_(True),
            )
        )
        if not coordinator_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Coordinator is not assigned to this group",
            )

    now = datetime.now(tz=UTC)
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
    summary="List every submitted passenger in a coordinator-assigned group",
)
async def list_my_group_passengers(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> list[AssignedPassengerResponse]:
    agency_id = _require_agency(current_user)
    await _ensure_group_assigned_to_coordinator(session, agency_id, group_id, current_user.id)
    result = await session.execute(
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    passengers = list(result.scalars().all())
    family_sizes = _family_sizes(passengers)
    return [
        AssignedPassengerResponse(
            id=passenger.id,
            client_name=passenger.client_name,
            client_email=passenger.client_email,
            client_phone=passenger.client_phone,
            departure_city=passenger.departure_city,
            submission_mode=passenger.submission_mode,
            family_group_id=passenger.family_group_id,
            family_group_label=_family_group_label(passenger, family_sizes),
            family_member_index=passenger.family_member_index,
            family_relation=passenger.family_relation,
            family_gender=passenger.family_gender,
            family_size=_family_size(passenger, family_sizes),
            family_head_name=passenger.family_head_name,
            status=passenger.status,
            coordinator_id=None,
            coordinator_name=None,
        )
        for passenger in passengers
    ]


@router.get(
    "/coordinator/groups/{group_id}/passengers/{passenger_id}",
    response_model=AssignedPassengerDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one submitted passenger from a coordinator-assigned group",
)
async def get_my_group_passenger_detail(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> AssignedPassengerDetailResponse:
    agency_id = _require_agency(current_user)
    await _ensure_group_assigned_to_coordinator(session, agency_id, group_id, current_user.id)
    result = await session.execute(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.id == passenger_id,
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
    )
    passenger = result.scalar_one_or_none()
    if not passenger:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passenger was not found in this group"
        )
    family_sizes = {passenger.family_group_id: 1} if passenger.family_group_id else {}
    return AssignedPassengerDetailResponse(
        id=passenger.id,
        client_name=passenger.client_name,
        client_email=passenger.client_email,
        client_phone=passenger.client_phone,
        departure_city=passenger.departure_city,
        submission_mode=passenger.submission_mode,
        family_group_id=passenger.family_group_id,
        family_group_label=_family_group_label(passenger, family_sizes),
        family_member_index=passenger.family_member_index,
        family_relation=passenger.family_relation,
        family_gender=passenger.family_gender,
        family_size=_family_size(passenger, family_sizes),
        family_head_name=passenger.family_head_name,
        status=passenger.status,
        coordinator_id=None,
        coordinator_name=None,
        qr_payload=None,
        created_at=passenger.created_at,
        updated_at=passenger.updated_at,
        client_reviewed_at=passenger.client_reviewed_at,
        confirmed_at=passenger.confirmed_at,
        passport_fields=passenger.confirmed_fields or passenger.extracted_fields or {},
        overall_confidence=passenger.overall_confidence,
    )


@router.post(
    "/coordinator/groups/{group_id}/sessions",
    response_model=AttendanceSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Reject coordinator attendance-activity creation attempts",
    deprecated=True,
)
async def create_my_attendance_session(
    group_id: uuid.UUID,
    body: CreateAttendanceSessionRequest,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceSessionResponse:
    agency_id = _require_agency(current_user)
    await _ensure_group_assigned_to_coordinator(session, agency_id, group_id, current_user.id)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Attendance activities must be created by an authorized manager or "
            "administrator. Select an activity already assigned to this group."
        ),
    )


@router.post(
    "/groups/{group_id}/attendance/sessions",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=AttendanceSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a canonical attendance activity as an authorized manager",
)
async def create_managed_attendance_session(
    group_id: uuid.UUID,
    body: CreateAttendanceSessionRequest,
    request: Request,
    current_user: User = Depends(require_role(ATTENDANCE_CLOSURE_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceSessionResponse:
    if current_user.role not in ATTENDANCE_CLOSURE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an authorized manager or administrator can create an attendance activity",
        )
    agency_id, _group = await _get_attendance_close_group_scope(
        session,
        group_id=group_id,
        current_user=current_user,
        lock_for_update=True,
    )
    attendance_session, outcome = await _create_canonical_attendance_activity(
        session,
        agency_id=agency_id,
        group_id=group_id,
        name=body.name,
        created_by_user_id=current_user.id,
        scheduled_starts_at=body.scheduled_starts_at,
        scheduled_ends_at=body.scheduled_ends_at,
        schedule_timezone=body.schedule_timezone,
    )
    response = await _attendance_session_response(session, attendance_session)
    if outcome != "existing":
        await append_attendance_realtime_invalidation(
            session,
            agency_id=agency_id,
            group_id=group_id,
            entity_type="attendance_session",
            entity_id=attendance_session.id,
            changed_by_user_id=current_user.id,
            occurred_at=attendance_session.updated_at,
        )
    await AuditLogRepository(session).record(
        action="attendance.activity_prepared",
        entity_type="attendance_session",
        agency_id=agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(attendance_session.id),
        ip_address=trusted_client_ip(request),
        metadata={
            "group_id": str(group_id),
            "outcome": outcome,
            "canonical_session_id": str(attendance_session.id),
        },
    )
    return response


@router.put(
    "/groups/{group_id}/attendance/sessions/{session_id}/schedule",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=AttendanceSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Set the authoritative schedule for an attendance activity",
)
async def update_managed_attendance_schedule(
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    body: UpdateAttendanceScheduleRequest,
    request: Request,
    current_user: User = Depends(require_role(ATTENDANCE_CLOSURE_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceSessionResponse:
    agency_id, _group = await _get_attendance_close_group_scope(
        session,
        group_id=group_id,
        current_user=current_user,
        lock_for_update=True,
    )
    attendance_session = await _get_managed_attendance_session(
        session,
        agency_id=agency_id,
        group_id=group_id,
        session_id=session_id,
    )
    if attendance_session.status not in {"draft", "active"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ATTENDANCE_SCHEDULE_LOCKED",
                "message": "Only a draft or active attendance activity can be rescheduled.",
            },
        )
    changed = (
        attendance_session.scheduled_starts_at != body.scheduled_starts_at
        or attendance_session.scheduled_ends_at != body.scheduled_ends_at
        or attendance_session.schedule_timezone != body.schedule_timezone
    )
    if changed:
        attendance_session.scheduled_starts_at = body.scheduled_starts_at
        attendance_session.scheduled_ends_at = body.scheduled_ends_at
        attendance_session.schedule_timezone = body.schedule_timezone
        attendance_session.schedule_version += 1
        attendance_session.updated_at = datetime.now(tz=UTC)
        await session.flush()
    await AuditLogRepository(session).record(
        action="attendance.activity_schedule_updated",
        entity_type="attendance_session",
        agency_id=agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(attendance_session.id),
        ip_address=trusted_client_ip(request),
        metadata={
            "group_id": str(group_id),
            "schedule_version": attendance_session.schedule_version,
            "scheduled_starts_at": body.scheduled_starts_at.isoformat(),
            "scheduled_ends_at": body.scheduled_ends_at.isoformat(),
            "schedule_timezone": body.schedule_timezone,
            "outcome": "updated" if changed else "already_current",
        },
    )
    return await _attendance_session_response(session, attendance_session)


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
            AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
        )
        .order_by(AttendanceSessionModel.created_at.desc())
    )
    return await _attendance_session_responses(
        session,
        list(result.scalars().all()),
        group_id,
    )


@router.get(
    "/coordinator/sessions/{session_id}/details",
    response_model=AttendanceSessionDetailsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get missing and scanned passengers for a coordinator attendance activity",
)
async def get_my_attendance_session_details(
    session_id: uuid.UUID,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceSessionDetailsResponse:
    agency_id = _require_agency(current_user)
    attendance_session = await _get_coordinator_attendance_session(
        session, agency_id, session_id, current_user.id
    )
    return await _attendance_session_details_response(session, attendance_session)


@router.post(
    "/coordinator/sessions/{session_id}/scan",
    response_model=AttendanceScanResponse,
    status_code=status.HTTP_200_OK,
    summary="Record one QR attendance scan for the current coordinator",
)
async def record_my_attendance_scan(
    session_id: uuid.UUID,
    body: AttendanceScanRequest,
    request: Request,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceScanResponse:
    agency_id = _require_agency(current_user)
    runtime = await resolve_browser_attendance_runtime(
        request,
        session=session,
        agency_id=agency_id,
        coordinator_user_id=current_user.id,
        required=body.runtime_id is not None,
    )
    if body.runtime_id is not None and (runtime is None or runtime.id != body.runtime_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ATTENDANCE_RUNTIME_MISMATCH",
                "message": "Refresh offline readiness before synchronizing scans.",
            },
        )
    attendance_session = await _get_coordinator_attendance_session(
        session,
        agency_id,
        session_id,
        current_user.id,
        lock_for_scan=True,
    )
    return await record_coordinator_attendance_scan(
        requested_session_id=session_id,
        body=body,
        request=request,
        current_user=current_user,
        session=session,
        agency_id=agency_id,
        attendance_session=attendance_session,
        runtime=runtime,
        dependencies=TourAttendanceScanDependencies(
            resolve_scannable_passenger=_resolve_scannable_passenger,
            insert_canonical_attendance_record=_insert_canonical_attendance_record,
            record_qr_audit=_record_qr_audit,
            attendance_scan_response=_attendance_scan_response,
        ),
    )


@router.post(
    "/coordinator/sessions/{session_id}/scan/batch",
    response_model=AttendanceScanBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Reconcile one bounded idempotent batch of offline attendance scans",
    dependencies=[Depends(require_cookie_csrf)],
)
async def record_coordinator_attendance_scan_batch(
    session_id: uuid.UUID,
    body: AttendanceScanBatchRequest,
    request: Request,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceScanBatchResponse:
    agency_id = _require_agency(current_user)
    runtime = await resolve_browser_attendance_runtime(
        request,
        session=session,
        agency_id=agency_id,
        coordinator_user_id=current_user.id,
        required=False,
    )
    attendance_session = await _get_coordinator_attendance_session(
        session,
        agency_id,
        session_id,
        current_user.id,
        lock_for_scan=True,
    )
    scan_dependencies = TourAttendanceScanDependencies(
        resolve_scannable_passenger=_resolve_scannable_passenger,
        insert_canonical_attendance_record=_insert_canonical_attendance_record,
        record_qr_audit=_record_qr_audit,
        attendance_scan_response=_attendance_scan_response,
    )
    return await process_coordinator_attendance_scan_batch(
        body=body,
        request=request,
        current_user=current_user,
        session=session,
        agency_id=agency_id,
        attendance_session=attendance_session,
        runtime=runtime,
        dependencies=AttendanceBatchDependencies(
            scan=scan_dependencies,
            attendance_scan_response=_attendance_scan_response,
        ),
    )


async def _load_attendance_closeout_status(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    attendance_session: AttendanceSessionModel,
) -> AttendanceCloseoutStatusResponse:
    closeout = await AttendanceCloseoutRepository(session).status(
        agency_id=agency_id,
        group_id=group_id,
        session_id=attendance_session.id,
        activity_valid_after=_attendance_activity_valid_after(attendance_session),
    )
    return _attendance_closeout_status_response(closeout)


@router.put(
    "/coordinator/groups/{group_id}/sessions/{session_id}/closeout-checkpoint",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=AttendanceCloseoutCheckpointResponse,
    status_code=status.HTTP_200_OK,
    summary="Publish count-only coordinator closeout evidence",
)
async def publish_my_attendance_closeout_checkpoint(
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    body: AttendanceCloseoutCheckpointRequest,
    request: Request,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceCloseoutCheckpointResponse:
    agency_id = _require_agency(current_user)
    runtime = await resolve_browser_attendance_runtime(
        request,
        session=session,
        agency_id=agency_id,
        coordinator_user_id=current_user.id,
        required=body.runtime_id is not None,
    )
    if body.runtime_id is not None and (runtime is None or runtime.id != body.runtime_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ATTENDANCE_RUNTIME_MISMATCH",
                "message": "Refresh offline readiness before publishing closeout evidence.",
            },
        )
    await _ensure_group_assigned_to_coordinator(
        session,
        agency_id,
        group_id,
        current_user.id,
    )
    attendance_session = await _get_coordinator_attendance_session(
        session,
        agency_id,
        session_id,
        current_user.id,
        lock_for_scan=True,
    )
    if attendance_session.group_id != group_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance activity was not found",
        )
    if attendance_session.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an active attendance activity accepts closeout checkpoints",
        )
    checkpoint = await AttendanceCloseoutRepository(session).publish(
        session_id=attendance_session.id,
        coordinator_user_id=current_user.id,
        counts=_attendance_closeout_counts(body),
        agency_id=agency_id,
        runtime_registration_id=runtime.id if runtime is not None else None,
    )
    await append_attendance_realtime_invalidation(
        session,
        agency_id=agency_id,
        group_id=group_id,
        entity_type="attendance_checkpoint",
        entity_id=attendance_session.id,
        changed_by_user_id=current_user.id,
        occurred_at=checkpoint.reported_at,
    )
    return AttendanceCloseoutCheckpointResponse(
        **body.model_dump(exclude={"runtime_id"}),
        runtime_id=runtime.id if runtime is not None else None,
        reported_at=checkpoint.reported_at,
    )


@router.put(
    "/coordinator/sessions/{session_id}/complete",
    response_model=AttendanceSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject coordinator global-close attempts for shared attendance",
    deprecated=True,
)
async def complete_my_attendance_session(
    session_id: uuid.UUID,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
) -> AttendanceSessionResponse:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only an authorized manager or administrator can close a shared attendance activity",
    )


@router.put(
    "/groups/{group_id}/attendance/sessions/{session_id}/complete",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=AttendanceSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Close a shared attendance activity as an authorized manager",
)
async def complete_managed_attendance_session(
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(ATTENDANCE_CLOSURE_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    body: AttendanceCloseRequest = AttendanceCloseRequest(),
) -> AttendanceSessionResponse:
    if current_user.role not in ATTENDANCE_CLOSURE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an authorized manager or administrator can close a shared attendance activity",
        )
    agency_id, _group = await _get_attendance_close_group_scope(
        session,
        group_id=group_id,
        current_user=current_user,
        lock_for_update=True,
    )
    attendance_session = await _get_managed_attendance_session(
        session,
        agency_id=agency_id,
        group_id=group_id,
        session_id=session_id,
    )
    if body.exception_reason is not None:
        try:
            await require_recent_mfa(request, current_user)
        except StepUpRequiredError:
            await AuditLogRepository(session).record(
                action="attendance.closeout_override_blocked",
                entity_type="attendance_session",
                agency_id=agency_id,
                user_id=current_user.id,
                actor_email=current_user.email,
                entity_id=str(attendance_session.id),
                ip_address=trusted_client_ip(request),
                result="blocked",
                metadata={
                    "group_id": str(group_id),
                    "reason": "recent_mfa_required",
                },
            )
            await session.commit()
            raise
    closeout: AttendanceCloseoutStatusResponse | None = None
    exception_used = False
    if attendance_session.status == "active":
        closeout = await _load_attendance_closeout_status(
            session,
            agency_id=agency_id,
            group_id=group_id,
            attendance_session=attendance_session,
        )
        exception_used = _require_attendance_closeout_clearance(
            closeout,
            exception_reason=body.exception_reason,
        )
    changed = await _close_shared_attendance_activity(session, attendance_session)
    response = await _attendance_session_response(session, attendance_session)
    if changed:
        if closeout is None:
            raise RuntimeError("Attendance closeout evidence was not evaluated")
        await append_attendance_realtime_invalidation(
            session,
            agency_id=agency_id,
            group_id=group_id,
            entity_type="attendance_session",
            entity_id=attendance_session.id,
            changed_by_user_id=current_user.id,
            occurred_at=attendance_session.updated_at,
        )
        await AuditLogRepository(session).record(
            action="attendance.activity_closed",
            entity_type="attendance_session",
            agency_id=agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            entity_id=str(attendance_session.id),
            ip_address=trusted_client_ip(request),
            metadata={
                "group_id": str(group_id),
                "server_scanned_count": response.scanned_count,
                "assigned_count": response.assigned_count,
                "late_offline_reconciliation_allowed": True,
                "closeout": _attendance_closeout_audit_metadata(
                    closeout,
                    exception_used=exception_used,
                    exception_reason=body.exception_reason,
                ),
            },
        )
    return response


@router.get(
    "/groups/{group_id}/attendance/sessions/{session_id}/closeout",
    response_model=AttendanceCloseoutStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get count-only coordinator-account closeout evidence for one activity",
)
async def get_managed_attendance_closeout_status(
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    current_user: User = Depends(require_role(ATTENDANCE_CLOSURE_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceCloseoutStatusResponse:
    if current_user.role not in ATTENDANCE_CLOSURE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an authorized manager or administrator can view closeout evidence",
        )
    agency_id, _group = await _get_attendance_close_group_scope(
        session,
        group_id=group_id,
        current_user=current_user,
    )
    attendance_session = await _get_managed_attendance_session(
        session,
        agency_id=agency_id,
        group_id=group_id,
        session_id=session_id,
        lock_for_update=False,
    )
    return await _load_attendance_closeout_status(
        session,
        agency_id=agency_id,
        group_id=group_id,
        attendance_session=attendance_session,
    )


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


@router.get(
    "/groups/{group_id}/attendance/summary",
    response_model=GroupAttendanceSummaryResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_304_NOT_MODIFIED: {
            "description": "The canonical attendance aggregate has not changed",
        },
    },
    summary="Get the lightweight canonical attendance aggregate for a group",
)
async def get_group_attendance_summary(
    group_id: uuid.UUID,
    request: Request,
    response: Response,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GroupAttendanceSummaryResponse | Response:
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(session, agency_id, group_id, current_user)
    projection = await AttendanceDashboardService(
        AttendanceDashboardRepository(session),
        AttendanceCloseoutRepository(session),
    ).summary(
        agency_id=agency_id,
        group_id=group.id,
        group_name=group.name,
    )
    etag, cache_headers = attendance_summary_cache_headers(projection.revision)
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=cache_headers)
    for name, value in cache_headers.items():
        response.headers[name] = value
    return attendance_summary_response(projection)


@router.get(
    "/groups/{group_id}/attendance/sessions/{session_id}/missing",
    response_model=AttendanceMissingPassengersPageResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "The canonical attendance snapshot changed",
        },
    },
    summary="List a coherent page of missing passengers for one activity",
)
async def get_group_attendance_missing_passengers(
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    revision: str = Query(
        ...,
        min_length=32,
        max_length=32,
        pattern="^[0-9a-f]+$",
    ),
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None, max_length=120),
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceMissingPassengersPageResponse | JSONResponse:
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(session, agency_id, group_id, current_user)
    normalized_search = " ".join(search.split()) if search else None
    try:
        projection = await AttendanceDashboardService(
            AttendanceDashboardRepository(session),
            AttendanceCloseoutRepository(session),
        ).missing_passengers(
            agency_id=agency_id,
            group_id=group.id,
            canonical_session_id=session_id,
            expected_revision=revision,
            cursor=cursor,
            limit=limit,
            search=normalized_search or None,
        )
    except AttendanceActivityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance activity was not found",
        ) from None
    except AttendanceSnapshotChangedError:
        return attendance_snapshot_changed_response()
    return attendance_missing_passengers_response(projection, page_size=limit)


async def _get_group(
    session: AsyncSession, agency_id: uuid.UUID, group_id: uuid.UUID
) -> ClientGroupModel:
    result = await session.execute(
        select(ClientGroupModel).where(
            ClientGroupModel.id == group_id, ClientGroupModel.agency_id == agency_id
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")
    return group


async def _lock_attendance_closeout_group(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> None:
    locked_group_id = await session.scalar(
        select(ClientGroupModel.id)
        .where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.status != GroupStatus.DELETED.value,
            ClientGroupModel.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if locked_group_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")


async def _get_manageable_group(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    current_user: User,
    *,
    lock_for_update: bool = False,
) -> ClientGroupModel:
    statement = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.status != "deleted",
    )
    if lock_for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")
    try:
        await AuthorizationPolicy(session).require_assign_coordinator(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    return group


async def _canonical_attendance_activity_admission(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    normalized_name: str,
) -> uuid.UUID | None:
    """Serialize canonical activity creation on the tenant-owned group row.

    Returning an existing open canonical UUID makes normalized retries
    idempotent. The group lock and database partial unique index together stop
    concurrent manager requests from admitting two open activities with the
    same normalized name.
    """

    locked_group_id = await session.scalar(
        select(ClientGroupModel.id)
        .where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.status != GroupStatus.DELETED.value,
            ClientGroupModel.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if locked_group_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")

    existing_id = await session.scalar(
        select(AttendanceSessionModel.id)
        .where(
            AttendanceSessionModel.agency_id == agency_id,
            AttendanceSessionModel.group_id == group_id,
            AttendanceSessionModel.normalized_name == normalized_name,
            AttendanceSessionModel.status.in_(("draft", "active")),
            AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
        )
        .order_by(AttendanceSessionModel.created_at, AttendanceSessionModel.id)
        .limit(1)
    )
    if existing_id is not None:
        return existing_id

    current = int(
        await session.scalar(
            select(func.count(AttendanceSessionModel.id)).where(
                AttendanceSessionModel.agency_id == agency_id,
                AttendanceSessionModel.group_id == group_id,
                AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
            )
        )
        or 0
    )
    maximum = get_settings().mobile.max_attendance_sessions_per_group
    if current >= maximum:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ATTENDANCE_SESSION_CAPACITY_REACHED",
                "message": (
                    f"This trip supports at most {maximum:,} attendance activities. "
                    "Archive or remove an existing activity before creating another."
                ),
            },
        )
    return None


async def _create_canonical_attendance_activity(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    name: str,
    created_by_user_id: uuid.UUID,
    scheduled_starts_at: datetime | None = None,
    scheduled_ends_at: datetime | None = None,
    schedule_timezone: str | None = None,
) -> tuple[AttendanceSessionModel, str]:
    """Create or resolve one manager-owned stable UUID for an open activity."""

    display_name = " ".join(name.split())
    normalized_name = normalize_attendance_activity_name(display_name)
    existing_id = await _canonical_attendance_activity_admission(
        session,
        agency_id=agency_id,
        group_id=group_id,
        normalized_name=normalized_name,
    )
    now = datetime.now(tz=UTC)
    inserted_id: uuid.UUID | None = None
    if existing_id is None:
        candidate_id = uuid.uuid4()
        inserted_id = (
            await session.execute(
                pg_insert(AttendanceSessionModel)
                .values(
                    id=candidate_id,
                    agency_id=agency_id,
                    group_id=group_id,
                    name=display_name,
                    normalized_name=normalized_name,
                    canonical_session_id=candidate_id,
                    status="active",
                    created_by_user_id=created_by_user_id,
                    created_at=now,
                    updated_at=now,
                    started_at=now,
                    scheduled_starts_at=scheduled_starts_at,
                    scheduled_ends_at=scheduled_ends_at,
                    schedule_timezone=schedule_timezone,
                )
                .on_conflict_do_nothing()
                .returning(AttendanceSessionModel.id)
            )
        ).scalar_one_or_none()

    target_id = inserted_id or existing_id
    lookup = select(AttendanceSessionModel).where(
        AttendanceSessionModel.agency_id == agency_id,
        AttendanceSessionModel.group_id == group_id,
        AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
    )
    if target_id is not None:
        lookup = lookup.where(AttendanceSessionModel.id == target_id)
    else:
        # A mixed-version deployment can still race an older writer that does
        # not take the group lock. Resolve the unique-index winner fail-safely.
        lookup = lookup.where(
            AttendanceSessionModel.normalized_name == normalized_name,
            AttendanceSessionModel.status.in_(("draft", "active")),
        )
    attendance_session = (await session.execute(lookup.limit(1))).scalar_one_or_none()
    if attendance_session is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The shared attendance activity changed while it was being created. Try again.",
        )

    if attendance_session.status == "draft":
        attendance_session.status = "active"
        attendance_session.started_at = attendance_session.started_at or now
        attendance_session.updated_at = now
        _apply_initial_attendance_schedule(
            attendance_session,
            scheduled_starts_at=scheduled_starts_at,
            scheduled_ends_at=scheduled_ends_at,
            schedule_timezone=schedule_timezone,
        )
        await session.flush()
        return attendance_session, "activated_existing"
    schedule_changed = _apply_initial_attendance_schedule(
        attendance_session,
        scheduled_starts_at=scheduled_starts_at,
        scheduled_ends_at=scheduled_ends_at,
        schedule_timezone=schedule_timezone,
    )
    if schedule_changed:
        attendance_session.updated_at = now
        await session.flush()
    return attendance_session, "created" if inserted_id is not None else "existing"


def _apply_initial_attendance_schedule(
    attendance_session: AttendanceSessionModel,
    *,
    scheduled_starts_at: datetime | None,
    scheduled_ends_at: datetime | None,
    schedule_timezone: str | None,
) -> bool:
    if scheduled_starts_at is None:
        return False
    existing = (
        attendance_session.scheduled_starts_at,
        attendance_session.scheduled_ends_at,
        attendance_session.schedule_timezone,
    )
    requested = (scheduled_starts_at, scheduled_ends_at, schedule_timezone)
    if all(value is None for value in existing):
        attendance_session.scheduled_starts_at = scheduled_starts_at
        attendance_session.scheduled_ends_at = scheduled_ends_at
        attendance_session.schedule_timezone = schedule_timezone
        return True
    if existing != requested:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ATTENDANCE_SCHEDULE_CONFLICT",
                "message": "The existing attendance activity has a different schedule.",
            },
        )
    return False


async def _get_managed_attendance_session(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    lock_for_update: bool = True,
) -> AttendanceSessionModel:
    statement = select(AttendanceSessionModel).where(
        AttendanceSessionModel.id == session_id,
        AttendanceSessionModel.canonical_session_id == session_id,
        AttendanceSessionModel.agency_id == agency_id,
        AttendanceSessionModel.group_id == group_id,
    )
    if lock_for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    attendance_session = result.scalar_one_or_none()
    if attendance_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance activity was not found",
        )
    return attendance_session


async def _get_attendance_close_group_scope(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    current_user: User,
    lock_for_update: bool = False,
) -> tuple[uuid.UUID, ClientGroupModel]:
    """Resolve the target tenant before closing, including global super admins."""

    if current_user.role != UserRole.SUPER_ADMIN or current_user.agency_id is not None:
        agency_id = _require_agency(current_user)
        group = await _get_manageable_group(
            session,
            agency_id,
            group_id,
            current_user,
            lock_for_update=lock_for_update,
        )
        return agency_id, group

    statement = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.status != "deleted",
    )
    if lock_for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    global_group = result.scalar_one_or_none()
    if global_group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")
    try:
        await AuthorizationPolicy(session).require_assign_coordinator(current_user, global_group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    return global_group.agency_id, global_group


async def _ensure_group_assigned_to_coordinator(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    coordinator_id: uuid.UUID,
) -> None:
    if not await AuthorizationPolicy(session).coordinator_has_group(coordinator_id, group_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group was not assigned to this coordinator",
        )


async def _get_coordinator_attendance_session(
    session: AsyncSession,
    agency_id: uuid.UUID,
    session_id: uuid.UUID,
    coordinator_id: uuid.UUID,
    *,
    lock_for_scan: bool = False,
) -> AttendanceSessionModel:
    requested_session = aliased(
        AttendanceSessionModel,
        name="requested_attendance_session",
    )
    canonical_session = aliased(
        AttendanceSessionModel,
        name="canonical_attendance_session",
    )
    statement = (
        select(canonical_session)
        .join(
            requested_session,
            requested_session.canonical_session_id == canonical_session.id,
        )
        .join(
            CoordinatorGroupAssignmentModel,
            CoordinatorGroupAssignmentModel.group_id == canonical_session.group_id,
        )
        .where(
            requested_session.id == session_id,
            requested_session.agency_id == agency_id,
            canonical_session.agency_id == agency_id,
            CoordinatorGroupAssignmentModel.agency_id == agency_id,
            CoordinatorGroupAssignmentModel.coordinator_user_id == coordinator_id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
    )
    if lock_for_scan:
        # Shared scan locks remain concurrent with one another but serialize
        # against the manager's exclusive global-close lock.
        statement = statement.with_for_update(read=True, of=canonical_session)
    result = await session.execute(statement)
    attendance_session = result.scalar_one_or_none()
    if not attendance_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attendance activity was not found"
        )
    return attendance_session


async def _attendance_session_response(
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
) -> AttendanceSessionResponse:
    counts = await _attendance_counts(
        session,
        attendance_session.id,
        attendance_session.group_id,
    )
    return AttendanceSessionResponse(
        id=attendance_session.id,
        group_id=attendance_session.group_id,
        name=attendance_session.name,
        status=attendance_session.status,
        created_at=attendance_session.created_at,
        started_at=attendance_session.started_at,
        completed_at=attendance_session.completed_at,
        scheduled_starts_at=attendance_session.scheduled_starts_at,
        scheduled_ends_at=attendance_session.scheduled_ends_at,
        schedule_timezone=attendance_session.schedule_timezone,
        schedule_version=attendance_session.schedule_version,
        scanned_count=counts["scanned"],
        assigned_count=counts["assigned"],
    )


async def _attendance_session_responses(
    session: AsyncSession,
    attendance_sessions: list[AttendanceSessionModel],
    group_id: uuid.UUID,
) -> list[AttendanceSessionResponse]:
    if not attendance_sessions:
        return []
    assigned_result = await session.execute(
        select(func.count(PassportSubmissionModel.id)).where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
    )
    assigned_count = int(assigned_result.scalar_one() or 0)
    session_ids = [attendance_session.id for attendance_session in attendance_sessions]
    family_session = aliased(
        AttendanceSessionModel,
        name="attendance_session_family",
    )
    scanned_result = await session.execute(
        select(
            family_session.canonical_session_id,
            func.count(func.distinct(AttendanceRecordModel.passenger_id)),
        )
        .select_from(family_session)
        .join(
            AttendanceRecordModel,
            AttendanceRecordModel.session_id == family_session.id,
        )
        .where(family_session.canonical_session_id.in_(session_ids))
        .group_by(family_session.canonical_session_id)
    )
    scanned_counts = {
        session_id: int(scanned_count) for session_id, scanned_count in scanned_result.all()
    }
    return [
        AttendanceSessionResponse(
            id=attendance_session.id,
            group_id=attendance_session.group_id,
            name=attendance_session.name,
            status=attendance_session.status,
            created_at=attendance_session.created_at,
            started_at=attendance_session.started_at,
            completed_at=attendance_session.completed_at,
            scheduled_starts_at=attendance_session.scheduled_starts_at,
            scheduled_ends_at=attendance_session.scheduled_ends_at,
            schedule_timezone=attendance_session.schedule_timezone,
            schedule_version=attendance_session.schedule_version,
            scanned_count=scanned_counts.get(attendance_session.id, 0),
            assigned_count=assigned_count,
        )
        for attendance_session in attendance_sessions
    ]


async def _attendance_scan_response(
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
    passenger_id: uuid.UUID | None,
    passenger_name: str | None,
    scan_status: str,
    message: str,
) -> AttendanceScanResponse:
    counts = await _attendance_counts(
        session,
        attendance_session.id,
        attendance_session.group_id,
    )
    return AttendanceScanResponse(
        session_id=attendance_session.id,
        passenger_id=passenger_id,
        passenger_name=passenger_name,
        status=scan_status,
        message=message,
        scanned_count=counts["scanned"],
        assigned_count=counts["assigned"],
    )


async def _attendance_session_details_response(
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
) -> AttendanceSessionDetailsResponse:
    counts = await _attendance_counts(
        session,
        attendance_session.id,
        attendance_session.group_id,
    )
    family_session = aliased(
        AttendanceSessionModel,
        name="attendance_session_family",
    )
    family_scans = (
        select(
            AttendanceRecordModel.passenger_id.label("passenger_id"),
            func.min(AttendanceRecordModel.scanned_at).label("scanned_at"),
        )
        .select_from(AttendanceRecordModel)
        .join(
            family_session,
            family_session.id == AttendanceRecordModel.session_id,
        )
        .where(
            family_session.canonical_session_id == attendance_session.id,
        )
        .group_by(AttendanceRecordModel.passenger_id)
        .subquery()
    )
    passengers_result = await session.execute(
        select(PassportSubmissionModel, family_scans.c.scanned_at)
        .outerjoin(
            family_scans,
            family_scans.c.passenger_id == PassportSubmissionModel.id,
        )
        .where(
            PassportSubmissionModel.agency_id == attendance_session.agency_id,
            PassportSubmissionModel.group_id == attendance_session.group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    passenger_statuses = [
        AttendancePassengerStatus(
            passenger_id=passenger.id,
            client_name=passenger.client_name,
            client_email=passenger.client_email,
            client_phone=passenger.client_phone,
            departure_city=passenger.departure_city,
            scanned=scanned_at is not None,
            scanned_at=scanned_at,
        )
        for passenger, scanned_at in passengers_result.all()
    ]
    scanned_passengers = [passenger for passenger in passenger_statuses if passenger.scanned]
    missing_passengers = [passenger for passenger in passenger_statuses if not passenger.scanned]
    return AttendanceSessionDetailsResponse(
        id=attendance_session.id,
        group_id=attendance_session.group_id,
        name=attendance_session.name,
        status=attendance_session.status,
        created_at=attendance_session.created_at,
        started_at=attendance_session.started_at,
        completed_at=attendance_session.completed_at,
        scanned_count=counts["scanned"],
        assigned_count=counts["assigned"],
        missing_passengers=missing_passengers,
        scanned_passengers=scanned_passengers,
        passengers=passenger_statuses,
    )


async def _attendance_counts(
    session: AsyncSession,
    session_id: uuid.UUID,
    group_id: uuid.UUID,
) -> dict[str, int]:
    assigned_count = (
        select(func.count(PassportSubmissionModel.id))
        .where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
        .scalar_subquery()
    )
    family_session = aliased(
        AttendanceSessionModel,
        name="attendance_session_family",
    )
    scanned_count = (
        select(func.count(func.distinct(AttendanceRecordModel.passenger_id)))
        .select_from(AttendanceRecordModel)
        .join(
            family_session,
            family_session.id == AttendanceRecordModel.session_id,
        )
        .where(
            family_session.canonical_session_id == session_id,
        )
        .scalar_subquery()
    )
    counts_result = await session.execute(select(assigned_count, scanned_count))
    assigned, scanned = counts_result.one()
    return {
        "assigned": int(assigned or 0),
        "scanned": int(scanned or 0),
    }


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
            AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
        )
        .order_by(AttendanceSessionModel.created_at.desc())
    )
    attendance_sessions = list(sessions_result.scalars().all())
    if not attendance_sessions:
        return GroupAttendanceOverviewResponse(
            group_id=group.id, group_name=group.name, sessions=[]
        )

    session_ids = [attendance_session.id for attendance_session in attendance_sessions]
    closeout_statuses = await AttendanceCloseoutRepository(session).statuses(
        agency_id=agency_id,
        group_id=group.id,
        activity_valid_after={
            attendance_session.id: _attendance_activity_valid_after(attendance_session)
            for attendance_session in attendance_sessions
        },
    )
    coordinators_result = await session.execute(
        select(
            CoordinatorGroupAssignmentModel.coordinator_user_id,
            UserModel.full_name,
        )
        .join(UserModel, UserModel.id == CoordinatorGroupAssignmentModel.coordinator_user_id)
        .where(
            CoordinatorGroupAssignmentModel.agency_id == agency_id,
            CoordinatorGroupAssignmentModel.group_id == group.id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
        .order_by(UserModel.full_name.asc())
    )
    group_coordinators = {
        row.coordinator_user_id: row.full_name for row in coordinators_result.all()
    }

    passenger_count_result = await session.execute(
        select(func.count(PassportSubmissionModel.id)).where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
    )
    passenger_count = int(passenger_count_result.scalar_one() or 0)

    family_session = aliased(
        AttendanceSessionModel,
        name="attendance_session_family",
    )
    scanned_result = await session.execute(
        select(
            family_session.canonical_session_id.label("canonical_session_id"),
            AttendanceRecordModel.passenger_id,
            AttendanceRecordModel.coordinator_user_id,
            AttendanceRecordModel.scanned_at,
            AttendanceRecordModel.id.label("attendance_record_id"),
        )
        .select_from(AttendanceRecordModel)
        .join(
            family_session,
            family_session.id == AttendanceRecordModel.session_id,
        )
        .where(family_session.canonical_session_id.in_(session_ids))
        .order_by(
            family_session.canonical_session_id,
            AttendanceRecordModel.passenger_id,
            AttendanceRecordModel.scanned_at,
            AttendanceRecordModel.id,
        )
    )
    scanned_counts: dict[tuple[uuid.UUID, uuid.UUID], int] = defaultdict(int)
    scanned_passenger_ids: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    seen_logical_passengers: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for row in scanned_result.all():
        logical_passenger = (row.canonical_session_id, row.passenger_id)
        if logical_passenger in seen_logical_passengers:
            continue
        seen_logical_passengers.add(logical_passenger)
        scanned_passenger_ids[row.canonical_session_id].add(row.passenger_id)
        scanned_counts[(row.canonical_session_id, row.coordinator_user_id)] += 1

    group_passengers_result = await session.execute(
        select(
            PassportSubmissionModel.id.label("passenger_id"),
            PassportSubmissionModel.client_name,
            PassportSubmissionModel.client_email,
            PassportSubmissionModel.client_phone,
            PassportSubmissionModel.departure_city,
        )
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    group_passengers = list(group_passengers_result.all())

    summaries: list[AttendanceSessionSummary] = []
    for attendance_session in attendance_sessions:
        coordinators = [
            AttendanceCoordinatorSummary(
                coordinator_id=coordinator_id,
                coordinator_name=name,
                assigned_count=passenger_count,
                scanned_count=scanned_counts.get((attendance_session.id, coordinator_id), 0),
            )
            for coordinator_id, name in group_coordinators.items()
        ]
        missing_passengers = [
            AttendanceMissingPassenger(
                passenger_id=row.passenger_id,
                client_name=row.client_name,
                client_email=row.client_email,
                client_phone=row.client_phone,
                departure_city=row.departure_city,
                coordinator_id=None,
                coordinator_name=None,
            )
            for row in group_passengers
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
                assigned_count=passenger_count,
                scanned_count=len(scanned_passenger_ids[attendance_session.id]),
                coordinators=coordinators,
                missing_passengers=missing_passengers,
                closeout=_attendance_closeout_status_response(
                    closeout_statuses[attendance_session.id]
                ),
            )
        )

    return GroupAttendanceOverviewResponse(
        group_id=group.id, group_name=group.name, sessions=summaries
    )


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
        .outerjoin(
            assignment_subquery, assignment_subquery.c.passenger_id == PassportSubmissionModel.id
        )
        .outerjoin(UserModel, UserModel.id == assignment_subquery.c.coordinator_id)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    rows = result.all()
    family_sizes = _family_sizes([row[0] for row in rows])
    return [
        AssignedPassengerResponse(
            id=passenger.id,
            client_name=passenger.client_name,
            client_email=passenger.client_email,
            client_phone=passenger.client_phone,
            departure_city=passenger.departure_city,
            submission_mode=passenger.submission_mode,
            family_group_id=passenger.family_group_id,
            family_group_label=_family_group_label(passenger, family_sizes),
            family_member_index=passenger.family_member_index,
            family_relation=passenger.family_relation,
            family_gender=passenger.family_gender,
            family_size=_family_size(passenger, family_sizes),
            family_head_name=passenger.family_head_name,
            status=passenger.status,
            coordinator_id=coordinator_id,
            coordinator_name=coordinator_name,
        )
        for passenger, coordinator_id, coordinator_name in rows
    ]


def _family_sizes(passengers: list[PassportSubmissionModel]) -> dict[uuid.UUID, int]:
    sizes: dict[uuid.UUID, int] = defaultdict(int)
    for passenger in passengers:
        if passenger.family_group_id:
            sizes[passenger.family_group_id] += 1
    return dict(sizes)


def _family_size(passenger: PassportSubmissionModel, family_sizes: dict[uuid.UUID, int]) -> int:
    if not passenger.family_group_id:
        return 1
    return max(1, family_sizes.get(passenger.family_group_id, 1))


def _family_group_label(
    passenger: PassportSubmissionModel, family_sizes: dict[uuid.UUID, int]
) -> str | None:
    if passenger.submission_mode != "family" or not passenger.family_group_id:
        return None
    family_size = _family_size(passenger, family_sizes)
    kind = "Couple" if family_size == 2 else "Family"
    return f"{passenger.family_head_name or passenger.client_name} {kind} ({family_size})"
