"""Passport excel exports: focused workflow boundary."""

from __future__ import annotations

import io
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.prepare_group_excel import (
    ExcelPreparationError,
    ExcelPreparationSupport,
    prepare_group_excel,
)
from app.application.use_cases.passports.prepare_tracking_excel import (
    TrackingExcelSupport,
    prepare_tracking_excel,
)
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.passport_image_zip_exporter import PassportImageZipExporter
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportHistoryRepository,
    PassportExportMode,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.response_contracts import XLSX, binary_responses
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportExportFieldOptionResponse,
    PassportExportFieldOptionsResponse,
    PassportExportGroupingOptionResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

from .constants import (
    _agency_match_export_field,
    _AgencyExportMatches,
    _apply_agency_export_matches,
    _apply_pending_export_fields,
    _export_additional_values,
    _export_agency_match_field_catalog,
    _export_agency_matches,
    _export_effective_whatsapp_matches,
    _export_field_catalog,
    _export_people_snapshot,
    _export_whatsapp_contacts,
    _export_whatsapp_match_rows,
    _export_zone_names_from_match_rows,
    _group_export_details,
    _international_airport_is_enabled,
    _pending_recipient_export_rows,
    _select_whatsapp_tracking_export_payload,
    _whatsapp_tracking_export_rows,
)
from .ecr_export_support import export_passport_ecr_results
from .export_context import (
    _current_group_export_submissions,
    _require_new_export_request,
    _resolve_export_group_by,
    _resolve_group_export_payload,
)
from .response_support import _owner_scope_for

router = APIRouter()

def group_excel_support() -> ExcelPreparationSupport:
    """Code-owned dependencies shared with MCP; never supplied by a request."""
    return ExcelPreparationSupport(
        _current_group_export_submissions=_current_group_export_submissions,
        _resolve_group_export_payload=_resolve_group_export_payload,
        _owner_scope_for=_owner_scope_for,
        _export_whatsapp_match_rows=_export_whatsapp_match_rows,
        _export_field_catalog=_export_field_catalog,
        _export_agency_match_field_catalog=_export_agency_match_field_catalog,
        _agency_match_export_field=_agency_match_export_field,
        _resolve_export_group_by=_resolve_export_group_by,
        _international_airport_is_enabled=_international_airport_is_enabled,
        _export_agency_matches=_export_agency_matches,
        _AgencyExportMatches=_AgencyExportMatches,
        _export_effective_whatsapp_matches=_export_effective_whatsapp_matches,
        _pending_recipient_export_rows=_pending_recipient_export_rows,
        _apply_pending_export_fields=_apply_pending_export_fields,
        _export_additional_values=_export_additional_values,
        _export_whatsapp_contacts=_export_whatsapp_contacts,
        _export_zone_names_from_match_rows=_export_zone_names_from_match_rows,
        _apply_agency_export_matches=_apply_agency_export_matches,
        _group_export_details=_group_export_details,
        export_passport_ecr_results=export_passport_ecr_results,
        _export_people_snapshot=_export_people_snapshot,
    )



@router.get(
    "/groups/{group_id}/export-fields",
    response_model=PassportExportFieldOptionsResponse,
    status_code=status.HTTP_200_OK,
    summary="List selectable supplemental columns for a passport Excel export",
)
async def get_passport_group_export_fields(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportExportFieldOptionsResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    group = await ClientGroupRepository(session).get_by_id(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        )

    submissions = await _current_group_export_submissions(
        session,
        group_id=group_id,
        agency_id=current_user.agency_id,
        current_user=current_user,
    )
    rows_by_group = await _export_whatsapp_match_rows(
        session,
        submissions,
        groups=[group],
    )
    catalog = _export_field_catalog(
        group,
        rows_by_group.get(group.id, []),
        submissions,
    )
    agency_match_catalog = _export_agency_match_field_catalog(
        group,
        rows_by_group.get(group.id, []),
    )
    default_selected = [str(field["key"]) for field in catalog if field["selected_by_default"]]
    return PassportExportFieldOptionsResponse(
        group_id=group.id,
        fields=[PassportExportFieldOptionResponse.model_validate(field) for field in catalog],
        agency_match_enabled=group.agency_dealership_name_enabled,
        agency_match_fields=[
            PassportExportFieldOptionResponse.model_validate(field)
            for field in agency_match_catalog
        ],
        grouping_fields=[
            *(
                [
                    PassportExportGroupingOptionResponse(
                        key="international_airport",
                        label="International Airport",
                        fixed=True,
                    )
                ]
                if _international_airport_is_enabled(group)
                else []
            ),
            *[
                PassportExportGroupingOptionResponse(
                    key=str(field["key"]),
                    label=str(field["label"]),
                    fixed=False,
                )
                for field in catalog
            ],
        ],
        default_selected_fields=default_selected,
        default_group_by_field=("zone_name" if "zone_name" in default_selected else None),
    )


def tracking_excel_support() -> TrackingExcelSupport:
    return TrackingExcelSupport(
        group_excel_support(), _whatsapp_tracking_export_rows,
        _select_whatsapp_tracking_export_payload,
    )


@router.get(
    "/groups/{group_id}/whatsapp-tracking/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export the selected WhatsApp submission tracking view to Excel",
response_class=Response, responses=binary_responses(XLSX))
async def export_whatsapp_tracking_by_group(
    group_id: uuid.UUID,
    tracking_status: Literal[
        "all",
        "submitted",
        "not_submitted",
        "multiple_submissions",
        "needs_review",
        "unmatched_submission",
        "replacement",
        "rejected_upload",
    ] = Query(default="all", alias="status"),
    broadcast_id: uuid.UUID | None = Query(default=None),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    group = await ClientGroupRepository(session).get_by_id(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        )

    submissions = await PassportSubmissionRepository(session).list_by_group(
        current_user.agency_id,
        group_id,
        limit=PassportImageZipExporter.MAX_SUBMISSIONS + 1,
        exclude_archived_groups=True,
        created_by_user_id=_owner_scope_for(current_user),
        visible_to_user=current_user,
    )
    if len(submissions) > PassportImageZipExporter.MAX_SUBMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                "A single export is limited to "
                f"{PassportImageZipExporter.MAX_SUBMISSIONS} passengers."
            ),
        )

    try:
        prepared = await prepare_tracking_excel(
            session,
            support=tracking_excel_support(),
            group=group,
            submissions=submissions,
            tracking_status=tracking_status,
            broadcast_id=broadcast_id,
        )
    except ExcelPreparationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    content = await prepared.render()
    await AuditLogRepository(session).record(
        action="passport_whatsapp_tracking_exported",
        entity_type="client_group",
        entity_id=str(group.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "tracking_status": tracking_status,
            "broadcast_id": str(broadcast_id) if broadcast_id else None,
            "submission_count": len(prepared.submissions),
            "pending_recipient_count": len(prepared.render_arguments["pending_rows"]),
            "workbook_bytes": len(content),
        },
    )
    await session.commit()

    filename = f"whatsapp-tracking-{group_id}-{tracking_status}.xlsx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/groups/{group_id}/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export a client group's passport submissions to Excel",
response_class=Response, responses=binary_responses(XLSX))
async def export_passports_by_group(
    group_id: uuid.UUID,
    export_mode: PassportExportMode = Query(default="all", alias="mode"),
    baseline_export_id: uuid.UUID | None = Query(default=None),
    request_id: uuid.UUID | None = Query(default=None),
    supplemental_fields: str | None = Query(default=None, max_length=20_000),
    group_by_field: str | None = Query(default=None, max_length=180),
    agency_match_field: str | None = Query(default=None, max_length=180),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    group_repo = ClientGroupRepository(session)
    group = await group_repo.get_by_id(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)

    resolved_request_id = request_id or uuid.uuid4()
    await _require_new_export_request(
        session, group_id=group_id, agency_id=current_user.agency_id,
        export_kind="passport_excel", request_id=resolved_request_id,
        created_by_user_id=_owner_scope_for(current_user),
    )
    try:
        prepared = await prepare_group_excel(
            session, support=group_excel_support(), current_user=current_user,
            agency_id=current_user.agency_id, group=group, export_mode=export_mode,
            baseline_export_id=baseline_export_id, supplemental_fields=supplemental_fields,
            group_by_field=group_by_field, agency_match_field=agency_match_field,
        )
    except ExcelPreparationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    content = await prepared.render()
    try:
        async with session.begin_nested():
            history = await PassportExportHistoryRepository(session).record(
                **{
                    **prepared.history_fields,
                    "artifact_metadata": {
                        **prepared.history_fields["artifact_metadata"],
                        "workbook_bytes": len(content),
                    },
                },
                request_id=resolved_request_id,
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This download request was already prepared by another "
                "request. Open download history or start a new download."
            ),
        ) from exc

    # Only persist a hidden prepared record here. The browser confirms it after
    # the complete response has been received and its download has been started.
    await session.commit()

    filename = f"passport-export-{group_id}.xlsx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Passport-Export-History-ID": str(history.id),
            "X-Content-Type-Options": "nosniff",
        },
    )
