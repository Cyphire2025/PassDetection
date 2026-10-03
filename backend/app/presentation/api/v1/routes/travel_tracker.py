"""Office travel readiness, bulk changes, and reviewable spreadsheet matching."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.exceptions.travel_tracker import TravelTrackerError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.travel_tracker.service import TravelTrackerService
from app.infrastructure.travel_tracker.spreadsheets import MAX_UPLOAD_BYTES
from app.presentation.api.v1.response_contracts import XLSX, binary_responses
from app.presentation.api.v1.schemas.travel_tracker_schemas import (
    TrackerGroupList,
    TrackerImportPreview,
    TrackerMarkRequest,
    TrackerMarkResponse,
    TrackerStatus,
    TrackerTrack,
    TrackerWorkspace,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
T = TypeVar("T")


async def _http_result(operation: Awaitable[T]) -> T:
    try:
        return await operation
    except TravelTrackerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/groups", response_model=TrackerGroupList)
async def list_tracker_groups(
    response: Response,
    search: Annotated[str | None, Query(max_length=160)] = None,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(24, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> TrackerGroupList:
    response.headers["Cache-Control"] = "no-store"
    return await _http_result(
        TravelTrackerService(session, current_user).list_groups(
            search=search, page=page, page_size=page_size
        )
    )


@router.get("/groups/{group_id}", response_model=TrackerWorkspace)
async def tracker_workspace(
    group_id: uuid.UUID,
    response: Response,
    track: TrackerTrack = "visa",
    status: TrackerStatus = "all",
    search: Annotated[str | None, Query(max_length=160)] = None,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(100, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> TrackerWorkspace:
    response.headers["Cache-Control"] = "no-store"
    return await _http_result(
        TravelTrackerService(session, current_user).workspace(
            group_id, track=track, status=status, search=search, page=page, page_size=page_size
        )
    )


@router.patch("/groups/{group_id}/marks", response_model=TrackerMarkResponse)
async def mark_tracker_passengers(
    group_id: uuid.UUID,
    body: TrackerMarkRequest,
    response: Response,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> TrackerMarkResponse:
    response.headers["Cache-Control"] = "no-store"
    return await _http_result(TravelTrackerService(session, current_user).mark(group_id, body))


@router.get("/groups/{group_id}/export", response_class=Response, responses=binary_responses(XLSX))
async def export_tracker_passengers(
    group_id: uuid.UUID,
    track: TrackerTrack = "visa",
    status: TrackerStatus = "all",
    search: Annotated[str | None, Query(max_length=160)] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    content, filename = await _http_result(
        TravelTrackerService(session, current_user).export(
            group_id, track=track, status=status, search=search
        )
    )
    return Response(
        content=content,
        media_type=XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/groups/{group_id}/import/preview", response_model=TrackerImportPreview)
async def preview_tracker_import(
    group_id: uuid.UUID,
    response: Response,
    file: UploadFile = File(...),
    track: TrackerTrack = Form("visa"),
    marked: bool = Form(True),
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> TrackerImportPreview:
    service = TravelTrackerService(session, current_user)
    await _http_result(service._group(group_id))
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload a file smaller than 8 MB.")
    response.headers["Cache-Control"] = "no-store"
    return await _http_result(
        service.preview(
            group_id, content=content, filename=file.filename or "", track=track, marked=marked
        )
    )
