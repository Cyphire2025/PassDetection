"""Attendance sessions for tour operations; preserve tenant, lock and transaction boundaries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.sync_journal import append_attendance_realtime_invalidation
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import AttendanceSessionModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AttendanceSessionDetailsResponse,
    AttendanceSessionResponse,
    CreateAttendanceSessionRequest,
    UpdateAttendanceScheduleRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip

from .tour_operations_access import (
    ATTENDANCE_CLOSURE_ROLES,
    _ensure_group_assigned_to_coordinator,
    _get_attendance_close_group_scope,
    _get_coordinator_attendance_session,
    _get_managed_attendance_session,
    _require_agency,
)
from .tour_operations_activity_lifecycle import _create_canonical_attendance_activity
from .tour_operations_attendance_views import (
    _attendance_session_details_response,
    _attendance_session_response,
    _attendance_session_responses,
)

router = APIRouter()


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
