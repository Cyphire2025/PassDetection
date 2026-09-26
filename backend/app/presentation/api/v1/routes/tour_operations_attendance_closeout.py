"""Attendance closeout for tour operations; preserve tenant, lock and transaction boundaries."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.sync_journal import append_attendance_realtime_invalidation
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import StepUpRequiredError
from app.infrastructure.database.models import AttendanceSessionModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutRepository,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
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
    close_shared_attendance_activity as _close_shared_attendance_activity,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    require_attendance_closeout_clearance as _require_attendance_closeout_clearance,
)
from app.presentation.api.v1.schemas.attendance_closeout_schemas import (
    AttendanceCloseoutCheckpointRequest,
    AttendanceCloseoutCheckpointResponse,
    AttendanceCloseoutStatusResponse,
    AttendanceCloseRequest,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import AttendanceSessionResponse
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.attendance_runtime import resolve_browser_attendance_runtime
from app.presentation.security.client_ip import trusted_client_ip

from .tour_operations_access import (
    ATTENDANCE_CLOSURE_ROLES,
    _ensure_group_assigned_to_coordinator,
    _get_attendance_close_group_scope,
    _get_coordinator_attendance_session,
    _get_managed_attendance_session,
    _require_agency,
)
from .tour_operations_attendance_views import _attendance_session_response

router = APIRouter()


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
