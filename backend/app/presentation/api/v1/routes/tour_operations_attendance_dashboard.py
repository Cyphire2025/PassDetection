"""Attendance dashboard for tour operations; preserve tenant, lock and transaction boundaries."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.attendance_dashboard import (
    AttendanceActivityNotFoundError,
    AttendanceDashboardService,
    AttendanceSnapshotChangedError,
)
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutRepository,
)
from app.infrastructure.repositories.attendance_dashboard_repository import (
    AttendanceDashboardRepository,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    attendance_missing_passengers_response,
    attendance_snapshot_changed_response,
    attendance_summary_cache_headers,
    attendance_summary_response,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    etag_matches as _etag_matches,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AttendanceMissingPassengersPageResponse,
    GroupAttendanceOverviewResponse,
    GroupAttendanceSummaryResponse,
)
from app.presentation.dependencies.auth import require_role

from .tour_operations_access import (
    COORDINATOR_MANAGEMENT_ROLES,
    _get_manageable_group,
    _require_agency,
)
from .tour_operations_attendance_views import _group_attendance_overview

router = APIRouter()


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
