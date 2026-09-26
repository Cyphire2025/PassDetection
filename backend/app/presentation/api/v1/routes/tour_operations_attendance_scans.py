"""Attendance scans for tour operations; preserve tenant, lock and transaction boundaries."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.tour_operations_attendance_batch_support import (
    AttendanceBatchDependencies,
    process_coordinator_attendance_scan_batch,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    TourAttendanceScanDependencies,
    record_coordinator_attendance_scan,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    insert_canonical_attendance_record as _insert_canonical_attendance_record,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    resolve_scannable_passenger as _resolve_scannable_passenger,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    record_qr_audit as _record_qr_audit,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AttendanceScanBatchRequest,
    AttendanceScanBatchResponse,
    AttendanceScanRequest,
    AttendanceScanResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.attendance_runtime import resolve_browser_attendance_runtime

from .tour_operations_access import _get_coordinator_attendance_session, _require_agency
from .tour_operations_attendance_views import _attendance_scan_response

router = APIRouter()


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
