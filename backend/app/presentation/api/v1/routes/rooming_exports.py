"""Hotel rooming: exports."""

from __future__ import annotations

import io
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.rooming.prepare_excel import (
    RoomingExcelSupport,
    RoomingPreparationError,
    prepare_checkins,
    prepare_rooming_list,
)
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.observability import metrics
from app.infrastructure.rooming.priority_fields import build_rooming_priority_context
from app.presentation.api.v1.download_headers import attachment_disposition
from app.presentation.api.v1.response_contracts import XLSX, binary_responses
from app.presentation.api.v1.routes.rooming_allocation_support import (
    room_number_sort_key as _room_number_sort_key,
)
from app.presentation.dependencies.auth import require_role

from .rooming_access import (
    _audit,
    _eligible_group_passengers,
    _export_filename,
    _get_rooming_hotel,
    _require_current_allocation,
    _stored_room_plan_matches,
)
from .rooming_checkin_reads import _checkin_dashboard
from .rooming_policy import ROOMING_ROLES

router = APIRouter()


def rooming_excel_support() -> RoomingExcelSupport:
    return RoomingExcelSupport(
        _require_current_allocation,
        _eligible_group_passengers,
        _room_number_sort_key,
        build_rooming_priority_context,
        _stored_room_plan_matches,
        _export_filename,
        _checkin_dashboard,
    )


@router.get(
    "/hotels/{hotel_id}/export.xlsx",
    summary="Download a hotel-ready rooming list workbook",
    response_class=Response,
    responses=binary_responses(XLSX),
)
async def export_hotel_rooming_list(
    hotel_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    hotel, group = await _get_rooming_hotel(session, hotel_id, current_user)
    try:
        prepared = await prepare_rooming_list(
            session,
            support=rooming_excel_support(),
            hotel=hotel,
            group=group,
        )
    except RoomingPreparationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    export_scope = prepared.scope
    filename = prepared.filename
    # All workbook inputs above are detached immutable projections. Release the
    # shared allocation/roster locks before CPU-heavy XLSX generation, then
    # reauthorize and revalidate the export scope before returning the bytes.
    await session.rollback()
    export_started = time.perf_counter()
    content = await prepared.render()
    metrics.observe(
        "rooming.export.generation_duration_ms",
        (time.perf_counter() - export_started) * 1_000,
    )
    metrics.observe("rooming.export.passenger_count", prepared.passenger_count)
    current_hotel, current_group = await _get_rooming_hotel(
        session,
        hotel_id,
        current_user,
    )
    await _require_current_allocation(session, current_hotel)
    current_export_scope = (
        current_hotel.allocation_revision,
        current_hotel.allocation_fingerprint,
        current_hotel.hotel_name,
        current_hotel.city,
        current_hotel.check_in_date,
        current_hotel.check_out_date,
        current_group.name,
        current_group.staff_code_enabled,
        current_group.agent_employee_code_enabled,
        current_group.travel_date,
    )
    if current_export_scope != export_scope:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rooming data changed during export. Generate the workbook again.",
        )
    await _audit(
        session,
        current_user,
        request,
        "rooming.rooming_list_exported",
        current_hotel,
        {
            "allocation_revision": current_hotel.allocation_revision,
            "passenger_count": prepared.passenger_count,
            "priority_fields": prepared.priority_fields,
        },
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": attachment_disposition(filename)},
    )


@router.get(
    "/hotels/{hotel_id}/check-ins/export.xlsx",
    summary="Export hotel check-in control sheet",
    response_class=Response,
    responses=binary_responses(XLSX),
)
async def export_hotel_checkins(
    hotel_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(ROOMING_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    hotel, group = await _get_rooming_hotel(session, hotel_id, current_user)
    try:
        prepared = await prepare_checkins(
            session,
            support=rooming_excel_support(),
            hotel=hotel,
            group=group,
        )
    except RoomingPreparationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    export_scope = prepared.scope
    export_filename = prepared.filename
    await session.rollback()
    export_started = time.perf_counter()
    content = await prepared.render()
    metrics.observe(
        "rooming.checkin_export.generation_duration_ms",
        (time.perf_counter() - export_started) * 1_000,
    )
    metrics.observe(
        "rooming.checkin_export.passenger_count",
        prepared.passenger_count,
    )
    current_hotel, current_group = await _get_rooming_hotel(
        session,
        hotel_id,
        current_user,
    )
    await _require_current_allocation(session, current_hotel)
    if (
        current_hotel.allocation_revision,
        current_hotel.allocation_fingerprint,
        current_hotel.hotel_name,
        current_group.name,
    ) != export_scope:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Check-in data changed during export. Generate the workbook again.",
        )
    await _audit(
        session,
        current_user,
        request,
        "rooming.checkin_exported",
        current_hotel,
        {},
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": attachment_disposition(export_filename)},
    )
