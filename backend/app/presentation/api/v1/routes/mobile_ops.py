"""Coordinator operations, push registration, and mobile notification feed."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.application.mobile.sync_journal import append_mobile_sync_change
from app.application.security.mobile_access_policy import MobileAccessPolicy
from app.core.config.settings import get_settings
from app.core.security.mobile_jwt import (
    MobileAccessClaims,
    hash_mobile_lookup,
)
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.domain.entities.entities import OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
from app.domain.exceptions.exceptions import AuthorizationError, EntityNotFoundError
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobileIdempotencyReceiptModel,
    MobileIncidentModel,
    MobileNotificationModel,
    MobilePassengerIdentityModel,
    MobilePushRegistrationModel,
)
from app.infrastructure.database.models import (
    AttendanceRecordModel,
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingHotelModel,
    RoomingRoomModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.tour_operations import (
    SCANNABLE_ATTENDANCE_STATUSES,
    _insert_canonical_attendance_record,
    _resolve_scannable_passenger,
    normalize_attendance_activity_name,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileAttendanceActionResult,
    MobileAttendanceBatchRequest,
    MobileAttendanceBatchResponse,
    MobileAttendanceMissingPassengerResponse,
    MobileAttendanceSessionCreateRequest,
    MobileAttendanceSessionDetailsResponse,
    MobileAttendanceSessionPageResponse,
    MobileAttendanceSessionResponse,
    MobileAttendanceSummaryResponse,
    MobileCoordinatorPassengerResponse,
    MobileCoordinatorRosterResponse,
    MobileIncidentActionResponse,
    MobileIncidentCreateRequest,
    MobileNotificationPageResponse,
    MobileNotificationReadResponse,
    MobileNotificationResponse,
    MobilePushRegistrationRequest,
    MobilePushRegistrationResponse,
    MobilePushUnregisterRequest,
    MobilePushUnregisterResponse,
)
from app.presentation.dependencies.mobile_auth import require_unrestricted_mobile_claims

router = APIRouter()

_APP_BUNDLE_ID = "com.globalconnects.groupcompanion"
_MAX_ROSTER_PAGE = 200
_MAX_NOTIFICATION_PAGE = 200
_MAX_ATTENDANCE_SESSION_PAGE = 100
_MAX_MISSING_PASSENGER_PAGE = 200
_MAX_SCAN_CLOCK_SKEW = timedelta(minutes=15)
_IDEMPOTENCY_RECEIPT_TTL = timedelta(days=30)


@router.get(
    "/coordinator/groups/{group_id}/passengers",
    response_model=MobileCoordinatorRosterResponse,
)
async def list_mobile_coordinator_passengers(
    group_id: uuid.UUID,
    search: str = Query(default="", max_length=120),
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=_MAX_ROSTER_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileCoordinatorRosterResponse:
    trip = await _require_coordinator_trip(session, claims, group_id)
    del trip

    employee_code = func.coalesce(
        PassportSubmissionModel.confirmed_fields["agent_employee_code"].as_string(),
        PassportSubmissionModel.staff_metadata["agent_employee_code"].as_string(),
        PassportSubmissionModel.staff_metadata["employee_code"].as_string(),
    )
    meal_preference = func.coalesce(
        PassportSubmissionModel.confirmed_fields["meal_preference"].as_string(),
        PassportSubmissionModel.staff_metadata["meal_preference"].as_string(),
    )
    room_number = (
        select(RoomingRoomModel.room_number)
        .join(RoomingAssignmentModel, RoomingAssignmentModel.room_id == RoomingRoomModel.id)
        .join(RoomingHotelModel, RoomingHotelModel.id == RoomingAssignmentModel.hotel_id)
        .where(
            RoomingAssignmentModel.passenger_id == PassportSubmissionModel.id,
            RoomingHotelModel.agency_id == claims.agency_id,
            RoomingHotelModel.group_id == group_id,
        )
        .order_by(RoomingHotelModel.check_in_date.desc(), RoomingHotelModel.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    filters = [
        PassportSubmissionModel.agency_id == claims.agency_id,
        PassportSubmissionModel.group_id == group_id,
        PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
    ]
    normalized_search = " ".join(search.split())
    if normalized_search:
        filters.append(
            or_(
                PassportSubmissionModel.client_name.icontains(
                    normalized_search, autoescape=True
                ),
                employee_code.icontains(normalized_search, autoescape=True),
            )
        )
    total = (
        await session.execute(select(func.count(PassportSubmissionModel.id)).where(*filters))
    ).scalar_one()
    if cursor is not None:
        filters.append(PassportSubmissionModel.id > cursor)
    rows = list(
        (
            await session.execute(
                select(
                    PassportSubmissionModel.id,
                    PassportSubmissionModel.client_name,
                    employee_code.label("employee_code"),
                    meal_preference.label("meal_preference"),
                    room_number.label("room_number"),
                )
                .where(*filters)
                .order_by(PassportSubmissionModel.id)
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    attendance_session = await _latest_attendance_session(session, claims, group_id)
    present_ids: set[uuid.UUID] = set()
    if attendance_session is not None and rows:
        present_ids = set(
            (
                await session.execute(
                    select(AttendanceRecordModel.passenger_id).where(
                        AttendanceRecordModel.agency_id == claims.agency_id,
                        AttendanceRecordModel.session_id == attendance_session.id,
                        AttendanceRecordModel.passenger_id.in_([row.id for row in rows]),
                    )
                )
            ).scalars()
        )
    session_completed = attendance_session is not None and attendance_session.status == "completed"
    return MobileCoordinatorRosterResponse(
        items=[
            MobileCoordinatorPassengerResponse(
                id=row.id,
                display_name=row.client_name,
                employee_code=_bounded_optional_text(row.employee_code, 120),
                attendance_status=(
                    "present"
                    if row.id in present_ids
                    else "missing"
                    if session_completed
                    else "not_marked"
                ),
                room_number=_bounded_optional_text(row.room_number, 80),
                meal_preference=_bounded_optional_text(row.meal_preference, 255),
                has_alert=False,
            )
            for row in rows
        ],
        next_cursor=str(rows[-1].id) if has_more and rows else None,
        total=int(total or 0),
    )


@router.get(
    "/coordinator/groups/{group_id}/passengers/{passenger_id}",
    response_model=MobileCoordinatorPassengerResponse,
)
async def get_mobile_coordinator_passenger(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileCoordinatorPassengerResponse:
    """Return one compact roster projection for incremental reconciliation."""

    await _require_coordinator_trip(session, claims, group_id)
    employee_code = func.coalesce(
        PassportSubmissionModel.confirmed_fields["agent_employee_code"].as_string(),
        PassportSubmissionModel.staff_metadata["agent_employee_code"].as_string(),
        PassportSubmissionModel.staff_metadata["employee_code"].as_string(),
    )
    meal_preference = func.coalesce(
        PassportSubmissionModel.confirmed_fields["meal_preference"].as_string(),
        PassportSubmissionModel.staff_metadata["meal_preference"].as_string(),
    )
    room_number = (
        select(RoomingRoomModel.room_number)
        .join(RoomingAssignmentModel, RoomingAssignmentModel.room_id == RoomingRoomModel.id)
        .join(RoomingHotelModel, RoomingHotelModel.id == RoomingAssignmentModel.hotel_id)
        .where(
            RoomingAssignmentModel.passenger_id == PassportSubmissionModel.id,
            RoomingHotelModel.agency_id == claims.agency_id,
            RoomingHotelModel.group_id == group_id,
        )
        .order_by(RoomingHotelModel.check_in_date.desc(), RoomingHotelModel.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    row = (
        await session.execute(
            select(
                PassportSubmissionModel.id,
                PassportSubmissionModel.client_name,
                employee_code.label("employee_code"),
                meal_preference.label("meal_preference"),
                room_number.label("room_number"),
            ).where(
                PassportSubmissionModel.id == passenger_id,
                PassportSubmissionModel.agency_id == claims.agency_id,
                PassportSubmissionModel.group_id == group_id,
                PassportSubmissionModel.status.in_(
                    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
                ),
            )
        )
    ).one_or_none()
    if row is None:
        raise EntityNotFoundError("Coordinator passenger", passenger_id)

    attendance_session = await _latest_attendance_session(session, claims, group_id)
    is_present = False
    if attendance_session is not None:
        is_present = bool(
            (
                await session.execute(
                    select(func.count(AttendanceRecordModel.id)).where(
                        AttendanceRecordModel.agency_id == claims.agency_id,
                        AttendanceRecordModel.session_id == attendance_session.id,
                        AttendanceRecordModel.passenger_id == passenger_id,
                    )
                )
            ).scalar_one()
        )
    session_completed = attendance_session is not None and attendance_session.status == "completed"
    return MobileCoordinatorPassengerResponse(
        id=row.id,
        display_name=row.client_name,
        employee_code=_bounded_optional_text(row.employee_code, 120),
        attendance_status=(
            "present" if is_present else "missing" if session_completed else "not_marked"
        ),
        room_number=_bounded_optional_text(row.room_number, 80),
        meal_preference=_bounded_optional_text(row.meal_preference, 255),
        has_alert=False,
    )


@router.get(
    "/coordinator/groups/{group_id}/attendance/sessions",
    response_model=MobileAttendanceSessionPageResponse,
)
async def list_mobile_attendance_sessions(
    group_id: uuid.UUID,
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=_MAX_ATTENDANCE_SESSION_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceSessionPageResponse:
    await _require_coordinator_trip(session, claims, group_id)
    statement = select(AttendanceSessionModel).where(
        AttendanceSessionModel.agency_id == claims.agency_id,
        AttendanceSessionModel.group_id == group_id,
        AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
    )
    if cursor is not None:
        statement = statement.where(AttendanceSessionModel.id < cursor)
    rows = list(
        (
            await session.execute(
                statement.order_by(AttendanceSessionModel.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = await _mobile_attendance_session_responses(
        session,
        claims=claims,
        group_id=group_id,
        attendance_sessions=rows,
    )
    return MobileAttendanceSessionPageResponse(
        items=items,
        next_cursor=str(rows[-1].id) if has_more and rows else None,
    )


@router.post(
    "/coordinator/groups/{group_id}/attendance/sessions",
    response_model=MobileAttendanceSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mobile_attendance_session(
    group_id: uuid.UUID,
    body: MobileAttendanceSessionCreateRequest,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceSessionResponse:
    await _require_coordinator_trip(session, claims, group_id)
    display_name = " ".join(body.name.split())
    normalized_name = normalize_attendance_activity_name(display_name)
    now = datetime.now(tz=UTC)
    candidate_id = uuid.uuid4()
    inserted_id = (
        await session.execute(
            pg_insert(AttendanceSessionModel)
            .values(
                id=candidate_id,
                agency_id=claims.agency_id,
                group_id=group_id,
                name=display_name,
                normalized_name=normalized_name,
                canonical_session_id=candidate_id,
                status="active",
                created_by_user_id=claims.principal_id,
                created_at=now,
                updated_at=now,
                started_at=now,
            )
            .on_conflict_do_nothing()
            .returning(AttendanceSessionModel.id)
        )
    ).scalar_one_or_none()
    attendance_session = (
        await session.execute(
            select(AttendanceSessionModel).where(
                AttendanceSessionModel.id == inserted_id
                if inserted_id is not None
                else (
                    (AttendanceSessionModel.agency_id == claims.agency_id)
                    & (AttendanceSessionModel.group_id == group_id)
                    & (AttendanceSessionModel.normalized_name == normalized_name)
                    & AttendanceSessionModel.status.in_(("draft", "active"))
                    & (
                        AttendanceSessionModel.id
                        == AttendanceSessionModel.canonical_session_id
                    )
                )
            )
        )
    ).scalar_one_or_none()
    if attendance_session is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attendance activity changed; synchronize and retry",
        )
    if attendance_session.status == "draft":
        attendance_session.status = "active"
        attendance_session.started_at = attendance_session.started_at or now
        attendance_session.updated_at = now
        await session.flush()
    return (
        await _mobile_attendance_session_responses(
            session,
            claims=claims,
            group_id=group_id,
            attendance_sessions=[attendance_session],
        )
    )[0]


@router.get(
    "/coordinator/groups/{group_id}/attendance/sessions/{session_id}",
    response_model=MobileAttendanceSessionDetailsResponse,
)
async def get_mobile_attendance_session_details(
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=_MAX_MISSING_PASSENGER_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceSessionDetailsResponse:
    await _require_coordinator_trip(session, claims, group_id)
    attendance_session = await _mobile_attendance_session(
        session,
        claims=claims,
        group_id=group_id,
        session_id=session_id,
        lock=False,
    )
    scanned_passengers = select(AttendanceRecordModel.passenger_id).where(
        AttendanceRecordModel.agency_id == claims.agency_id,
        AttendanceRecordModel.session_id == attendance_session.id,
    )
    filters = [
        PassportSubmissionModel.agency_id == claims.agency_id,
        PassportSubmissionModel.group_id == group_id,
        PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
        PassportSubmissionModel.id.not_in(scanned_passengers),
    ]
    if cursor is not None:
        filters.append(PassportSubmissionModel.id > cursor)
    missing_rows = list(
        (
            await session.execute(
                select(
                    PassportSubmissionModel.id,
                    PassportSubmissionModel.client_name,
                )
                .where(*filters)
                .order_by(PassportSubmissionModel.id)
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(missing_rows) > limit
    missing_rows = missing_rows[:limit]
    summary = (
        await _mobile_attendance_session_responses(
            session,
            claims=claims,
            group_id=group_id,
            attendance_sessions=[attendance_session],
        )
    )[0]
    return MobileAttendanceSessionDetailsResponse(
        session=summary,
        missing=[
            MobileAttendanceMissingPassengerResponse(
                id=row.id,
                display_name=row.client_name,
            )
            for row in missing_rows
        ],
        next_cursor=(
            str(missing_rows[-1].id) if has_more and missing_rows else None
        ),
    )


@router.put(
    "/coordinator/groups/{group_id}/attendance/sessions/{session_id}/complete",
    response_model=MobileAttendanceSessionResponse,
)
async def complete_mobile_attendance_session(
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceSessionResponse:
    await _require_coordinator_trip(session, claims, group_id)
    attendance_session = await _mobile_attendance_session(
        session,
        claims=claims,
        group_id=group_id,
        session_id=session_id,
        lock=True,
    )
    if attendance_session.status != "completed":
        now = datetime.now(tz=UTC)
        attendance_session.status = "completed"
        attendance_session.completed_at = now
        attendance_session.updated_at = now
        await session.flush()
    return (
        await _mobile_attendance_session_responses(
            session,
            claims=claims,
            group_id=group_id,
            attendance_sessions=[attendance_session],
        )
    )[0]


@router.post(
    "/coordinator/groups/{group_id}/attendance/actions",
    response_model=MobileAttendanceBatchResponse,
)
async def apply_mobile_attendance_actions(
    group_id: uuid.UUID,
    body: MobileAttendanceBatchRequest,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceBatchResponse:
    trip = await _require_coordinator_trip(session, claims, group_id)
    now = datetime.now(tz=UTC)
    results: list[MobileAttendanceActionResult] = []
    for action in body.actions:
        if action.scanned_at > now + _MAX_SCAN_CLOCK_SKEW:
            results.append(
                MobileAttendanceActionResult(
                    client_event_id=action.client_event_id,
                    status="rejected",
                    reason_code="SCANNED_AT_IN_FUTURE",
                )
            )
            continue
        attendance_session = await _attendance_session_for_action(
            session,
            claims,
            group_id,
            requested_session_id=action.session_id,
        )
        if attendance_session is None:
            results.append(
                MobileAttendanceActionResult(
                    client_event_id=action.client_event_id,
                    status="refresh_required",
                    reason_code="ATTENDANCE_SESSION_SELECTION_REQUIRED",
                )
            )
            continue
        if (
            attendance_session.started_at is not None
            and action.scanned_at
            < attendance_session.started_at - _MAX_SCAN_CLOCK_SKEW
        ) or (
            attendance_session.completed_at is not None
            and action.scanned_at
            > attendance_session.completed_at + _MAX_SCAN_CLOCK_SKEW
        ):
            results.append(
                MobileAttendanceActionResult(
                    client_event_id=action.client_event_id,
                    status="rejected",
                    reason_code="SCANNED_OUTSIDE_SESSION_WINDOW",
                )
            )
            continue
        passenger, _token, rejection_reason = await _resolve_scannable_passenger(
            session=session,
            agency_id=claims.agency_id,
            group_id=group_id,
            qr_payload=action.signed_qr,
        )
        if passenger is None:
            results.append(
                MobileAttendanceActionResult(
                    client_event_id=action.client_event_id,
                    status="rejected",
                    reason_code=_attendance_rejection_code(rejection_reason),
                )
            )
            continue
        inserted_id = await _insert_canonical_attendance_record(
            session=session,
            agency_id=claims.agency_id,
            attendance_session=attendance_session,
            passenger_id=passenger.id,
            coordinator_user_id=claims.principal_id,
            scanned_at=action.scanned_at.astimezone(UTC),
            sync_source="offline",
            client_event_id=str(action.client_event_id),
            device_id=str(claims.session_id),
        )
        if inserted_id is None:
            replay_state = await _attendance_replay_state(
                session,
                claims=claims,
                attendance_session=attendance_session,
                passenger_id=passenger.id,
                client_event_id=str(action.client_event_id),
            )
            if replay_state == "event_reused":
                results.append(
                    MobileAttendanceActionResult(
                        client_event_id=action.client_event_id,
                        status="rejected",
                        reason_code="IDEMPOTENCY_KEY_REUSED",
                    )
                )
                continue
            if replay_state == "unknown":
                results.append(
                    MobileAttendanceActionResult(
                        client_event_id=action.client_event_id,
                        status="refresh_required",
                        reason_code="ATTENDANCE_CONFLICT",
                    )
                )
                continue
        else:
            changed_at = datetime.now(tz=UTC)
            attendance_session.updated_at = changed_at
            await append_mobile_sync_change(
                session,
                access=trip.access,
                audience="coordinator",
                entity_type="coordinator_passenger",
                entity_id=passenger.id,
                operation="upsert",
                version=max(0, int(changed_at.timestamp() * 1000)),
                changed_by_user_id=claims.principal_id,
                payload={
                    "resource_path": (
                        f"/api/v1/mobile/coordinator/groups/{group_id}/passengers/"
                        f"{passenger.id}"
                    )
                },
            )
        results.append(
            MobileAttendanceActionResult(
                client_event_id=action.client_event_id,
                status="accepted" if inserted_id is not None else "already_applied",
                server_version=None,
                reason_code=None,
            )
        )
    return MobileAttendanceBatchResponse(results=results)


async def _attendance_replay_state(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    attendance_session: AttendanceSessionModel,
    passenger_id: uuid.UUID,
    client_event_id: str,
) -> str:
    """Distinguish a safe retry from a reused offline idempotency key."""

    family_session = aliased(
        AttendanceSessionModel,
        name="mobile_attendance_session_family",
    )
    rows = list(
        (
            await session.execute(
                select(
                    AttendanceRecordModel.passenger_id,
                    AttendanceRecordModel.client_event_id,
                )
                .join(
                    family_session,
                    family_session.id == AttendanceRecordModel.session_id,
                )
                .where(
                    AttendanceRecordModel.agency_id == claims.agency_id,
                    family_session.canonical_session_id == attendance_session.id,
                    or_(
                        AttendanceRecordModel.passenger_id == passenger_id,
                        AttendanceRecordModel.client_event_id == client_event_id,
                    ),
                )
                .limit(2)
            )
        ).all()
    )
    if any(
        row.client_event_id == client_event_id and row.passenger_id != passenger_id
        for row in rows
    ):
        return "event_reused"
    if rows:
        return "already_applied"
    return "unknown"


@router.get(
    "/coordinator/groups/{group_id}/attendance/summary",
    response_model=MobileAttendanceSummaryResponse,
)
async def get_mobile_attendance_summary(
    group_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceSummaryResponse:
    trip = await _require_coordinator_trip(session, claims, group_id)
    attendance_session = await _latest_attendance_session(session, claims, group_id)
    total = (
        await session.execute(
            select(func.count(PassportSubmissionModel.id)).where(
                PassportSubmissionModel.agency_id == claims.agency_id,
                PassportSubmissionModel.group_id == group_id,
                PassportSubmissionModel.status.in_(
                    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
                ),
            )
        )
    ).scalar_one()
    present = 0
    updated_at = trip.access.updated_at
    if attendance_session is not None:
        present = int(
            (
                await session.execute(
                    select(func.count(AttendanceRecordModel.id)).where(
                        AttendanceRecordModel.agency_id == claims.agency_id,
                        AttendanceRecordModel.session_id == attendance_session.id,
                    )
                )
            ).scalar_one()
            or 0
        )
        updated_at = attendance_session.updated_at
    total_count = int(total or 0)
    unmarked = max(0, total_count - present)
    completed = attendance_session is not None and attendance_session.status == "completed"
    return MobileAttendanceSummaryResponse(
        trip_id=group_id,
        total=total_count,
        present=present,
        missing=unmarked if completed else 0,
        excused=0,
        not_marked=0 if completed else unmarked,
        version=max(0, int(updated_at.timestamp() * 1000)),
        updated_at=updated_at,
    )


@router.post(
    "/coordinator/groups/{group_id}/incidents",
    response_model=MobileIncidentActionResponse,
)
async def create_mobile_incident(
    group_id: uuid.UUID,
    body: MobileIncidentCreateRequest,
    request: Request,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileIncidentActionResponse:
    trip = await _require_coordinator_trip(session, claims, group_id)
    now = datetime.now(tz=UTC)
    occurred_at = body.occurred_at.astimezone(UTC)
    if occurred_at > now + _MAX_SCAN_CLOCK_SKEW:
        return MobileIncidentActionResponse(
            client_event_id=body.client_event_id,
            status="rejected",
            reason_code="OCCURRED_AT_IN_FUTURE",
        )

    request_payload = body.model_dump(mode="json")
    request_hash = hashlib.sha256(
        json.dumps(
            request_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    idempotency_key = str(body.client_event_id)
    receipt_id = uuid.uuid4()
    inserted_receipt_id = (
        await session.execute(
            pg_insert(MobileIdempotencyReceiptModel)
            .values(
                id=receipt_id,
                agency_id=claims.agency_id,
                session_id=claims.session_id,
                group_id=group_id,
                gc_group_access_id=trip.access.id,
                idempotency_key=idempotency_key,
                operation="incident.create",
                request_hash=request_hash,
                status="processing",
                response_payload={},
                created_at=now,
                expires_at=now + _IDEMPOTENCY_RECEIPT_TTL,
            )
            .on_conflict_do_nothing(
                index_elements=["session_id", "idempotency_key"]
            )
            .returning(MobileIdempotencyReceiptModel.id)
        )
    ).scalar_one_or_none()
    receipt_lookup = select(MobileIdempotencyReceiptModel)
    if inserted_receipt_id is not None:
        receipt_lookup = receipt_lookup.where(
            MobileIdempotencyReceiptModel.id == inserted_receipt_id
        )
    else:
        receipt_lookup = receipt_lookup.where(
            MobileIdempotencyReceiptModel.agency_id == claims.agency_id,
            MobileIdempotencyReceiptModel.session_id == claims.session_id,
            MobileIdempotencyReceiptModel.idempotency_key == idempotency_key,
        )
    receipt = (
        await session.execute(receipt_lookup.with_for_update())
    ).scalar_one_or_none()
    if receipt is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Incident receipt changed; retry with the same event identifier",
        )
    if not hmac.compare_digest(receipt.request_hash, request_hash):
        return MobileIncidentActionResponse(
            client_event_id=body.client_event_id,
            status="rejected",
            reason_code="IDEMPOTENCY_KEY_REUSED",
        )
    if receipt.status == "completed" and receipt.resource_id is not None:
        return MobileIncidentActionResponse(
            client_event_id=body.client_event_id,
            status="already_applied",
            incident_id=receipt.resource_id,
        )

    incident = (
        await session.execute(
            select(MobileIncidentModel).where(
                MobileIncidentModel.agency_id == claims.agency_id,
                MobileIncidentModel.group_id == group_id,
                MobileIncidentModel.gc_group_access_id == trip.access.id,
                MobileIncidentModel.created_by_session_id == claims.session_id,
                MobileIncidentModel.client_event_id == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    created = incident is None
    if incident is None:
        incident = MobileIncidentModel(
            id=uuid.uuid4(),
            agency_id=claims.agency_id,
            group_id=group_id,
            gc_group_access_id=trip.access.id,
            created_by_session_id=claims.session_id,
            reported_by_user_id=claims.principal_id,
            affected_passenger_identity_id=None,
            client_event_id=idempotency_key,
            incident_type="other",
            severity=body.severity,
            status="open",
            title=body.title,
            description=body.description,
            location_text=None,
            is_confidential=True,
            occurred_at=occurred_at,
            created_offline_at=(
                occurred_at if occurred_at < now - timedelta(minutes=1) else None
            ),
            acknowledged_at=None,
            resolved_at=None,
            resolved_by_user_id=None,
            resolution_note=None,
            created_at=now,
            updated_at=now,
        )
        session.add(incident)
        await session.flush()
        await append_mobile_sync_change(
            session,
            access=trip.access,
            audience="coordinator",
            entity_type="incident",
            entity_id=incident.id,
            operation="upsert",
            version=trip.access.manifest_version,
            changed_by_user_id=claims.principal_id,
            payload={
                "resource_path": f"/api/v1/mobile/coordinator/groups/{group_id}/incidents"
            },
        )
        await AuditLogRepository(session).record(
            action="mobile.incident_created",
            entity_type="mobile_incident",
            agency_id=claims.agency_id,
            user_id=claims.principal_id,
            entity_id=str(incident.id),
            ip_address=request.client.host if request.client else None,
            metadata={
                "group_id": str(group_id),
                "severity": body.severity,
                "created_offline": incident.created_offline_at is not None,
            },
        )

    response_payload = {
        "client_event_id": idempotency_key,
        "status": "accepted" if created else "already_applied",
        "incident_id": str(incident.id),
        "reason_code": None,
    }
    receipt.status = "completed"
    receipt.response_status_code = status.HTTP_200_OK
    receipt.response_payload = response_payload
    receipt.response_hash = hashlib.sha256(
        json.dumps(response_payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    receipt.resource_type = "mobile_incident"
    receipt.resource_id = incident.id
    receipt.completed_at = now
    return MobileIncidentActionResponse(
        client_event_id=body.client_event_id,
        status="accepted" if created else "already_applied",
        incident_id=incident.id,
    )


@router.post("/push/register", response_model=MobilePushRegistrationResponse)
async def register_mobile_push_token(
    body: MobilePushRegistrationRequest,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobilePushRegistrationResponse:
    now = datetime.now(tz=UTC)
    device_session = await _current_device_session(session, claims)
    expected_device_hash = hash_mobile_lookup(
        body.installation_id, purpose="device-installation"
    )
    if not hmac.compare_digest(expected_device_hash, device_session.device_identifier_hash):
        raise AuthorizationError("Push registration is not available")
    if (body.provider == "fcm" and device_session.platform != "android") or (
        body.provider == "apns" and device_session.platform != "ios"
    ):
        raise AuthorizationError("Push registration is not available")

    token_hash = hash_mobile_lookup(body.push_token, purpose="push-token")
    registration = (
        await session.execute(
            select(MobilePushRegistrationModel)
            .where(
                MobilePushRegistrationModel.provider == body.provider,
                MobilePushRegistrationModel.token_lookup_hash == token_hash,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if registration is not None and registration.session_id != claims.session_id:
        old_session = (
            await session.execute(
                select(MobileDeviceSessionModel).where(
                    MobileDeviceSessionModel.id == registration.session_id
                )
            )
        ).scalar_one_or_none()
        if old_session is None or not hmac.compare_digest(
            old_session.device_identifier_hash, device_session.device_identifier_hash
        ):
            raise AuthorizationError("Push registration is not available")

    ciphertext = _push_fernet().encrypt(body.push_token.encode("utf-8"))
    if registration is None:
        registration = MobilePushRegistrationModel(
            id=uuid.uuid4(),
            agency_id=claims.agency_id,
            session_id=claims.session_id,
            provider=body.provider,
            platform=device_session.platform,
            environment="production" if get_settings().is_production else "development",
            app_bundle_id=_APP_BUNDLE_ID,
            token_ciphertext=ciphertext,
            token_lookup_hash=token_hash,
            token_key_version=1,
            status="active",
            notifications_authorized=True,
            last_registered_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(registration)
    else:
        registration.agency_id = claims.agency_id
        registration.session_id = claims.session_id
        registration.platform = device_session.platform
        registration.environment = (
            "production" if get_settings().is_production else "development"
        )
        registration.app_bundle_id = _APP_BUNDLE_ID
        registration.token_ciphertext = ciphertext
        registration.token_key_version = 1
        registration.status = "active"
        registration.notifications_authorized = True
        registration.last_registered_at = now
        registration.last_failure_at = None
        registration.last_failure_code = None
        registration.revoked_at = None
        registration.updated_at = now

    previous_rows = list(
        (
            await session.execute(
                select(MobilePushRegistrationModel).where(
                    MobilePushRegistrationModel.session_id == claims.session_id,
                    MobilePushRegistrationModel.agency_id == claims.agency_id,
                    MobilePushRegistrationModel.provider == body.provider,
                    MobilePushRegistrationModel.id != registration.id,
                    MobilePushRegistrationModel.status == "active",
                )
            )
        ).scalars()
    )
    for previous in previous_rows:
        previous.status = "revoked"
        previous.revoked_at = now
        previous.updated_at = now
    await session.flush()
    return MobilePushRegistrationResponse(registration_id=registration.id)


@router.post("/push/unregister", response_model=MobilePushUnregisterResponse)
async def unregister_mobile_push_token(
    body: MobilePushUnregisterRequest,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobilePushUnregisterResponse:
    device_session = await _current_device_session(session, claims)
    expected_device_hash = hash_mobile_lookup(
        body.installation_id, purpose="device-installation"
    )
    if not hmac.compare_digest(expected_device_hash, device_session.device_identifier_hash):
        raise AuthorizationError("Push registration is not available")
    statement = select(MobilePushRegistrationModel).where(
        MobilePushRegistrationModel.session_id == claims.session_id,
        MobilePushRegistrationModel.agency_id == claims.agency_id,
        MobilePushRegistrationModel.status != "revoked",
    )
    if body.provider is not None:
        statement = statement.where(MobilePushRegistrationModel.provider == body.provider)
    rows = list((await session.execute(statement.with_for_update())).scalars())
    now = datetime.now(tz=UTC)
    for registration in rows:
        registration.status = "revoked"
        registration.notifications_authorized = False
        registration.revoked_at = now
        registration.updated_at = now
    return MobilePushUnregisterResponse(revoked_count=len(rows))


@router.get("/notifications", response_model=MobileNotificationPageResponse)
async def list_mobile_notifications(
    trip_id: uuid.UUID | None = Query(default=None),
    cursor: uuid.UUID | None = Query(default=None),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=_MAX_NOTIFICATION_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileNotificationPageResponse:
    if trip_id is not None:
        await MobileAccessPolicy(session).require_trip_access(claims, trip_id)
    now = datetime.now(tz=UTC)
    recipient_filter = _notification_recipient_filter(claims)
    accessible_groups = _accessible_group_ids(claims, now)
    filters = [
        MobileNotificationModel.agency_id == claims.agency_id,
        recipient_filter,
        # A provider delivery failure must not remove the durable in-app update.
        MobileNotificationModel.status.in_(("queued", "sent", "failed")),
        MobileNotificationModel.available_at <= now,
        or_(
            MobileNotificationModel.expires_at.is_(None),
            MobileNotificationModel.expires_at > now,
        ),
        or_(
            MobileNotificationModel.group_id.is_(None),
            MobileNotificationModel.group_id.in_(accessible_groups),
        ),
    ]
    if trip_id is not None:
        filters.append(MobileNotificationModel.group_id == trip_id)
    if unread_only:
        filters.append(MobileNotificationModel.read_at.is_(None))
    unread_count = (
        await session.execute(
            select(func.count(MobileNotificationModel.id)).where(
                *filters,
                MobileNotificationModel.read_at.is_(None),
            )
        )
    ).scalar_one()
    if cursor is not None:
        filters.append(MobileNotificationModel.id < cursor)
    rows = list(
        (
            await session.execute(
                select(MobileNotificationModel)
                .where(*filters)
                .order_by(MobileNotificationModel.id.desc())
                .limit(limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return MobileNotificationPageResponse(
        items=[_notification_response(item) for item in rows],
        next_cursor=str(rows[-1].id) if has_more and rows else None,
        unread_count=int(unread_count or 0),
    )


@router.post(
    "/notifications/{notification_id}/read",
    response_model=MobileNotificationReadResponse,
)
async def mark_mobile_notification_read(
    notification_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileNotificationReadResponse:
    notification = (
        await session.execute(
            select(MobileNotificationModel)
            .where(
                MobileNotificationModel.id == notification_id,
                MobileNotificationModel.agency_id == claims.agency_id,
                _notification_recipient_filter(claims),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if notification is None:
        raise EntityNotFoundError("Mobile notification", notification_id)
    if notification.group_id is not None:
        await MobileAccessPolicy(session).require_trip_access(claims, notification.group_id)
    if notification.read_at is None:
        notification.read_at = datetime.now(tz=UTC)
        notification.updated_at = notification.read_at
    return MobileNotificationReadResponse(id=notification.id, read_at=notification.read_at)


async def _require_coordinator_trip(
    session: AsyncSession,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
):
    if claims.principal_type != "coordinator":
        raise AuthorizationError("Coordinator group access is required")
    return await MobileAccessPolicy(session).require_trip_access(claims, group_id)


async def _mobile_attendance_session(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    lock: bool,
) -> AttendanceSessionModel:
    statement = select(AttendanceSessionModel).where(
        AttendanceSessionModel.id == session_id,
        AttendanceSessionModel.canonical_session_id == session_id,
        AttendanceSessionModel.agency_id == claims.agency_id,
        AttendanceSessionModel.group_id == group_id,
    )
    if lock:
        statement = statement.with_for_update()
    value = (await session.execute(statement)).scalar_one_or_none()
    if value is None:
        raise EntityNotFoundError("Attendance activity", session_id)
    return value


async def _mobile_attendance_session_responses(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    attendance_sessions: list[AttendanceSessionModel],
) -> list[MobileAttendanceSessionResponse]:
    if not attendance_sessions:
        return []
    assigned_count = int(
        (
            await session.execute(
                select(func.count(PassportSubmissionModel.id)).where(
                    PassportSubmissionModel.agency_id == claims.agency_id,
                    PassportSubmissionModel.group_id == group_id,
                    PassportSubmissionModel.status.in_(
                        OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
                    ),
                )
            )
        ).scalar_one()
        or 0
    )
    ids = [item.id for item in attendance_sessions]
    scan_counts = dict(
        (
            await session.execute(
                select(
                    AttendanceRecordModel.session_id,
                    func.count(func.distinct(AttendanceRecordModel.passenger_id)),
                )
                .where(
                    AttendanceRecordModel.agency_id == claims.agency_id,
                    AttendanceRecordModel.session_id.in_(ids),
                )
                .group_by(AttendanceRecordModel.session_id)
            )
        ).all()
    )
    return [
        MobileAttendanceSessionResponse(
            id=item.id,
            name=item.name,
            status=item.status,
            scanned_count=int(scan_counts.get(item.id, 0)),
            assigned_count=assigned_count,
            started_at=item.started_at,
            completed_at=item.completed_at,
        )
        for item in attendance_sessions
    ]


async def _latest_attendance_session(
    session: AsyncSession,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
) -> AttendanceSessionModel | None:
    return (
        await session.execute(
            select(AttendanceSessionModel)
            .where(
                AttendanceSessionModel.agency_id == claims.agency_id,
                AttendanceSessionModel.group_id == group_id,
                AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
                AttendanceSessionModel.status.in_(SCANNABLE_ATTENDANCE_STATUSES),
            )
            .order_by(
                case((AttendanceSessionModel.status == "active", 0), else_=1),
                AttendanceSessionModel.updated_at.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def _attendance_session_for_action(
    session: AsyncSession,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    *,
    requested_session_id: uuid.UUID | None,
) -> AttendanceSessionModel | None:
    statement = select(AttendanceSessionModel).where(
        AttendanceSessionModel.agency_id == claims.agency_id,
        AttendanceSessionModel.group_id == group_id,
        AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
        AttendanceSessionModel.status.in_(SCANNABLE_ATTENDANCE_STATUSES),
    )
    if requested_session_id is not None:
        return (
            await session.execute(
                statement.where(AttendanceSessionModel.id == requested_session_id).limit(1)
            )
        ).scalar_one_or_none()
    candidates = list(
        (
            await session.execute(
                statement.order_by(AttendanceSessionModel.updated_at.desc()).limit(2)
            )
        ).scalars()
    )
    return candidates[0] if len(candidates) == 1 else None


async def _current_device_session(
    session: AsyncSession,
    claims: MobileAccessClaims,
) -> MobileDeviceSessionModel:
    value = (
        await session.execute(
            select(MobileDeviceSessionModel).where(
                MobileDeviceSessionModel.id == claims.session_id,
                MobileDeviceSessionModel.agency_id == claims.agency_id,
                MobileDeviceSessionModel.status == "active",
                MobileDeviceSessionModel.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if value is None:
        raise AuthorizationError("Mobile device session is not available")
    return value


def _push_fernet() -> Fernet:
    """Compatibility shim for focused registration tests."""

    return mobile_push_fernet()


def _notification_recipient_filter(claims: MobileAccessClaims):
    if claims.principal_type == "passenger":
        return (
            (MobileNotificationModel.recipient_type == "passenger")
            & (MobileNotificationModel.recipient_passenger_identity_id == claims.principal_id)
            & MobileNotificationModel.recipient_user_id.is_(None)
        )
    return (
        (MobileNotificationModel.recipient_type == claims.principal_type)
        & (MobileNotificationModel.recipient_user_id == claims.principal_id)
        & MobileNotificationModel.recipient_passenger_identity_id.is_(None)
    )


def _accessible_group_ids(claims: MobileAccessClaims, now: datetime):
    statement = (
        select(GCGroupAccessModel.group_id)
        .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
        .where(
            GCGroupAccessModel.agency_id == claims.agency_id,
            ClientGroupModel.agency_id == claims.agency_id,
            ClientGroupModel.status.in_(("active", "closed")),
            ClientGroupModel.deleted_at.is_(None),
            GCGroupAccessModel.is_enabled.is_(True),
            GCGroupAccessModel.revoked_at.is_(None),
            or_(
                GCGroupAccessModel.access_starts_at.is_(None),
                GCGroupAccessModel.access_starts_at <= now,
            ),
            or_(
                GCGroupAccessModel.access_expires_at.is_(None),
                GCGroupAccessModel.access_expires_at > now,
            ),
        )
    )
    if claims.principal_type == "passenger":
        statement = statement.join(
            MobilePassengerIdentityModel,
            MobilePassengerIdentityModel.gc_group_access_id == GCGroupAccessModel.id,
        ).where(
            GCGroupAccessModel.passenger_access_enabled.is_(True),
            MobilePassengerIdentityModel.id == claims.principal_id,
            MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
            MobilePassengerIdentityModel.revoked_at.is_(None),
        )
    elif claims.principal_type == "client_manager":
        statement = (
            statement.join(
                ClientManagerGroupAssignmentModel,
                ClientManagerGroupAssignmentModel.gc_group_access_id == GCGroupAccessModel.id,
            )
            .join(
                ClientManagerProfileModel,
                ClientManagerProfileModel.id
                == ClientManagerGroupAssignmentModel.profile_id,
            )
            .where(
                GCGroupAccessModel.client_manager_access_enabled.is_(True),
                ClientManagerProfileModel.user_id == claims.principal_id,
                ClientManagerProfileModel.status == "active",
                ClientManagerProfileModel.deleted_at.is_(None),
                ClientManagerGroupAssignmentModel.is_active.is_(True),
                ClientManagerGroupAssignmentModel.revoked_at.is_(None),
            )
        )
    else:
        statement = statement.join(
            CoordinatorGroupAssignmentModel,
            CoordinatorGroupAssignmentModel.group_id == GCGroupAccessModel.group_id,
        ).where(
            GCGroupAccessModel.coordinator_access_enabled.is_(True),
            CoordinatorGroupAssignmentModel.coordinator_user_id == claims.principal_id,
            CoordinatorGroupAssignmentModel.agency_id == claims.agency_id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
    return statement.scalar_subquery()


def _notification_response(item: MobileNotificationModel) -> MobileNotificationResponse:
    return MobileNotificationResponse(
        id=item.id,
        trip_id=item.group_id,
        notification_type=item.notification_type,
        category=item.category,
        priority=_mobile_priority(item.priority),
        title=item.title,
        body=item.body,
        deep_link_path=item.deep_link_path,
        payload=_safe_public_payload(item.public_payload),
        available_at=item.available_at,
        expires_at=item.expires_at,
        read_at=item.read_at,
    )


def _safe_public_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, object] = {}
    for key in ("screen", "group_id", "entity_id", "category"):
        item = value.get(key)
        if isinstance(item, (str, int, bool)) and len(str(item)) <= 512:
            safe[key] = item
    return safe


def _mobile_priority(value: str) -> str:
    if value == "emergency":
        return "emergency"
    if value == "high":
        return "important"
    return "normal"


def _attendance_rejection_code(value: str | None) -> str:
    mapping = {
        "unknown_token": "QR_UNKNOWN",
        "revoked": "QR_REVOKED",
        "expired": "QR_EXPIRED",
        "inactive": "QR_INACTIVE",
        "wrong_group": "QR_WRONG_GROUP",
    }
    return mapping.get(value or "", "QR_INVALID")


def _bounded_optional_text(value: object, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:max_length] or None
