"""Passport excel exports: focused workflow boundary."""

from __future__ import annotations

import asyncio
import io
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.passport_excel_exporter import PassportExcelExporter
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
from .export_context import (
    _current_group_export_submissions,
    _require_new_export_request,
    _resolve_export_group_by,
    _resolve_group_export_payload,
)
from .response_support import _owner_scope_for

router = APIRouter()


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


@router.get(
    "/groups/{group_id}/whatsapp-tracking/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export the selected WhatsApp submission tracking view to Excel",
)
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

    linked_broadcasts, tracking_rows = await _whatsapp_tracking_export_rows(
        session,
        group=group,
        submissions=submissions,
    )
    if not linked_broadcasts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Link at least one WhatsApp broadcast before exporting tracking.",
        )
    if broadcast_id is not None and broadcast_id not in linked_broadcasts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The selected WhatsApp broadcast is not linked to this client group.",
        )

    selected_submissions, selected_rows = _select_whatsapp_tracking_export_payload(
        submissions,
        tracking_rows,
        tracking_status=tracking_status,
        broadcast_id=broadcast_id,
    )
    rows_by_group = {group.id: selected_rows}
    catalog = _export_field_catalog(group, selected_rows, selected_submissions)
    selected_fields = [field for field in catalog if field["selected_by_default"]]
    selected_field_keys = [str(field["key"]) for field in selected_fields]
    resolved_group_by = _resolve_export_group_by(None, selected_field_keys)
    pending_rows = _pending_recipient_export_rows(
        group=group,
        rows=selected_rows,
    )
    if pending_rows:
        _apply_pending_export_fields(
            pending_rows,
            selected_rows,
            selected_fields,
        )

    content = await asyncio.to_thread(
        PassportExcelExporter().export_group,
        selected_submissions,
        group_name=group.name,
        group_details={group.id: _group_export_details(group)},
        zone_names=_export_zone_names_from_match_rows(
            selected_submissions,
            rows_by_group,
        ),
        additional_fields=[
            {"key": str(field["key"]), "label": str(field["label"])} for field in selected_fields
        ],
        additional_values=_export_additional_values(
            selected_submissions,
            rows_by_group,
            selected_fields,
        ),
        whatsapp_contacts=_export_whatsapp_contacts(
            selected_submissions,
            rows_by_group,
        ),
        group_by_field=resolved_group_by,
        pending_rows=pending_rows,
    )
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
            "submission_count": len(selected_submissions),
            "pending_recipient_count": len(pending_rows),
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
)
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

    current_submissions = await _current_group_export_submissions(
        session,
        group_id=group_id,
        agency_id=current_user.agency_id,
        current_user=current_user,
    )
    resolved_request_id = request_id or uuid.uuid4()
    await _require_new_export_request(
        session,
        group_id=group_id,
        agency_id=current_user.agency_id,
        export_kind="passport_excel",
        request_id=resolved_request_id,
        created_by_user_id=_owner_scope_for(current_user),
    )
    submissions, baseline = await _resolve_group_export_payload(
        session,
        group_id=group_id,
        agency_id=current_user.agency_id,
        export_kind="passport_excel",
        export_mode=export_mode,
        baseline_export_id=baseline_export_id,
        submissions=current_submissions,
        created_by_user_id=_owner_scope_for(current_user),
    )
    match_rows_by_group = await _export_whatsapp_match_rows(
        session,
        current_submissions,
        groups=[group],
    )
    catalog = _export_field_catalog(
        group,
        match_rows_by_group.get(group.id, []),
        current_submissions,
    )
    catalog_by_key = {str(field["key"]): field for field in catalog}
    requested_field_keys = (
        list(dict.fromkeys(key.strip() for key in supplemental_fields.split(",") if key.strip()))
        if supplemental_fields is not None
        else [str(field["key"]) for field in catalog if field["selected_by_default"]]
    )
    unknown_fields = [key for key in requested_field_keys if key not in catalog_by_key]
    if unknown_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more selected Excel fields are unavailable for this group.",
        )
    resolved_agency_match_field = (
        agency_match_field.strip() if agency_match_field and agency_match_field.strip() else None
    )
    agency_match_option: dict[str, str | bool] | None = None
    if resolved_agency_match_field:
        if not group.agency_dealership_name_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Agency matching is available only when Agency/Dealership "
                    "Name is enabled for the group."
                ),
            )
        agency_match_catalog = _export_agency_match_field_catalog(
            group,
            match_rows_by_group.get(group.id, []),
        )
        agency_match_options = {str(field["key"]): field for field in agency_match_catalog}
        agency_match_option = agency_match_options.get(resolved_agency_match_field)
        if agency_match_option is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "The selected agency matching field is unavailable for "
                    "this group's linked WhatsApp spreadsheets."
                ),
            )
        # The matching field is automatic and must never be duplicated in the
        # user-selected supplemental field list.
        requested_field_keys = [
            key for key in requested_field_keys if key != resolved_agency_match_field
        ]
    selected_fields = [catalog_by_key[key] for key in requested_field_keys]
    export_fields = (
        [_agency_match_export_field(agency_match_option), *selected_fields]
        if agency_match_option is not None
        else selected_fields
    )
    resolved_group_by = _resolve_export_group_by(
        group_by_field,
        requested_field_keys,
    )
    if resolved_group_by == resolved_agency_match_field:
        resolved_group_by = None
    if resolved_group_by == "international_airport" and not _international_airport_is_enabled(
        group
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "International Airport grouping is available only when the "
                "group asks travellers for that field."
            ),
        )
    if (
        resolved_group_by
        and resolved_group_by != "international_airport"
        and resolved_group_by not in requested_field_keys
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "The grouping field must be International Airport or an included WhatsApp field."
            ),
        )
    agency_matches = (
        _export_agency_matches(
            submissions,
            match_rows_by_group,
            resolved_agency_match_field,
        )
        if resolved_agency_match_field
        else _AgencyExportMatches({}, frozenset())
    )
    effective_matches = (
        _export_effective_whatsapp_matches(
            agency_matches,
            match_rows_by_group,
        )
        if resolved_agency_match_field
        else agency_matches
    )
    pending_rows = (
        _pending_recipient_export_rows(
            group=group,
            rows=match_rows_by_group.get(group.id, []),
            excluded_recipient_ids=effective_matches.matched_recipient_ids,
            include_name_history=bool(resolved_agency_match_field),
        )
        if export_mode == "all"
        else []
    )
    if pending_rows:
        _apply_pending_export_fields(
            pending_rows,
            match_rows_by_group.get(group.id, []),
            export_fields,
            excluded_recipient_ids=effective_matches.matched_recipient_ids,
        )
    additional_values: dict[uuid.UUID, dict[str, str | None]]
    whatsapp_contacts: dict[uuid.UUID, dict[str, str | None]]
    zone_names: dict[uuid.UUID, str]
    if resolved_agency_match_field:
        # Each submission receives one coherent WhatsApp row: prefer the
        # selected agency match, then fall back to its existing identity match.
        additional_values = {submission.id: {} for submission in submissions}
        whatsapp_contacts = {
            submission.id: {"email": None, "phone": None} for submission in submissions
        }
        zone_names = {submission.id: "" for submission in submissions}
    else:
        additional_values = _export_additional_values(
            submissions,
            match_rows_by_group,
            selected_fields,
        )
        whatsapp_contacts = _export_whatsapp_contacts(
            submissions,
            match_rows_by_group,
        )
        zone_names = _export_zone_names_from_match_rows(
            submissions,
            match_rows_by_group,
        )
    previous_names = (
        _apply_agency_export_matches(
            effective_matches,
            selected_fields,
            resolved_agency_match_field,
            additional_values=additional_values,
            whatsapp_contacts=whatsapp_contacts,
            zone_names=zone_names,
        )
        if resolved_agency_match_field
        else None
    )
    content = await asyncio.to_thread(
        PassportExcelExporter().export_group,
        submissions,
        group_name=group.name,
        group_details={group.id: _group_export_details(group)},
        zone_names=zone_names,
        additional_fields=[
            {"key": str(field["key"]), "label": str(field["label"])} for field in export_fields
        ],
        additional_values=additional_values,
        whatsapp_contacts=whatsapp_contacts,
        previous_names=previous_names,
        group_by_field=resolved_group_by,
        pending_rows=pending_rows,
    )
    try:
        async with session.begin_nested():
            history = await PassportExportHistoryRepository(session).record(
                group_id=group_id,
                agency_id=current_user.agency_id,
                export_kind="passport_excel",
                export_mode=export_mode,
                request_id=resolved_request_id,
                baseline_export_id=baseline.id if baseline else None,
                snapshot_submission_ids=[submission.id for submission in current_submissions],
                exported_submission_ids=[submission.id for submission in submissions],
                exported_people_snapshot=_export_people_snapshot(submissions),
                pending_recipient_count=len(pending_rows),
                artifact_metadata={
                    "workbook_bytes": len(content),
                    "supplemental_fields": requested_field_keys,
                    "group_by_field": resolved_group_by,
                    "agency_match_field": resolved_agency_match_field,
                    "agency_matched_submission_count": len(agency_matches.rows_by_submission),
                },
                created_by_user_id=current_user.id,
                actor_email=current_user.email,
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
