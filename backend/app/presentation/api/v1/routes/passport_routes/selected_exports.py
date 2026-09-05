"""Passport selected exports: focused workflow boundary."""

from __future__ import annotations

import asyncio
import io
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import ClientGroup, PassportSubmission, User, UserRole
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.passport_excel_exporter import PassportExcelExporter
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    ExportSelectedGroupsRequest,
    ExportSelectedPassportsRequest,
    PassportExportFieldOptionResponse,
    PassportExportGroupingOptionResponse,
    PassportSelectedGroupsExportFieldOptionsResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

from .constants import (
    PASSPORT_COMBINED_EXPORT_MAX_ROWS,
    _apply_pending_export_fields,
    _combined_export_field_catalog,
    _export_additional_values,
    _export_group_details,
    _export_whatsapp_contacts,
    _export_whatsapp_match_rows,
    _export_zone_names_from_match_rows,
    _group_export_details,
    _international_airport_is_enabled,
    _pending_recipient_export_rows,
)
from .export_context import _resolve_export_group_by
from .response_support import _apply_manager_visibility, _submitted_statuses

router = APIRouter()


@router.post(
    "/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export selected passport submissions to Excel",
)
async def export_selected_passports(
    body: ExportSelectedPassportsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    stmt = (
        select(PassportSubmissionModel)
        .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        .where(
            PassportSubmissionModel.id.in_(body.submission_ids),
            PassportSubmissionModel.status.in_(_submitted_statuses()),
            operational_roster_member(),
        )
    )
    stmt = _apply_manager_visibility(stmt, current_user)
    result = await session.execute(stmt)
    submissions = [
        PassportSubmissionRepository._to_entity(model) for model in result.scalars().all()
    ]
    if not submissions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No exportable passport submissions found"
        )

    match_rows_by_group = await _export_whatsapp_match_rows(session, submissions)
    content = await asyncio.to_thread(
        PassportExcelExporter().export_group,
        submissions,
        group_name="Selected Passports",
        group_details=await _export_group_details(
            session, [submission.group_id for submission in submissions]
        ),
        zone_names=_export_zone_names_from_match_rows(
            submissions,
            match_rows_by_group,
        ),
        whatsapp_contacts=_export_whatsapp_contacts(
            submissions,
            match_rows_by_group,
        ),
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="selected-passports.xlsx"'},
    )


@router.post(
    "/groups/export-fields",
    response_model=PassportSelectedGroupsExportFieldOptionsResponse,
    status_code=status.HTTP_200_OK,
    summary="List combined Excel fields for selected passport groups",
)
async def get_selected_groups_export_fields(
    body: ExportSelectedGroupsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSelectedGroupsExportFieldOptionsResponse:
    groups, submissions = await _selected_groups_export_context(
        group_ids=body.group_ids,
        current_user=current_user,
        session=session,
    )
    match_rows_by_group = await _export_whatsapp_match_rows(
        session,
        submissions,
        groups=groups,
    )
    catalog = _combined_export_field_catalog(
        groups,
        match_rows_by_group,
        submissions,
    )
    default_selected = [str(field["key"]) for field in catalog if field["selected_by_default"]]
    return PassportSelectedGroupsExportFieldOptionsResponse(
        group_ids=[group.id for group in groups],
        fields=[PassportExportFieldOptionResponse.model_validate(field) for field in catalog],
        grouping_fields=[
            *(
                [
                    PassportExportGroupingOptionResponse(
                        key="international_airport",
                        label="International Airport",
                        fixed=True,
                    )
                ]
                if any(_international_airport_is_enabled(group) for group in groups)
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


async def _selected_groups_export_context(
    *,
    group_ids: list[uuid.UUID],
    current_user: User,
    session: AsyncSession,
) -> tuple[list[ClientGroup], list[PassportSubmission]]:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    ordered_group_ids = list(dict.fromkeys(group_ids))
    group_stmt = select(ClientGroupModel).where(ClientGroupModel.id.in_(ordered_group_ids))
    group_stmt = AuthorizationPolicy.apply_group_visibility_scope(
        group_stmt,
        current_user,
    )
    group_result = await session.execute(group_stmt)
    groups_by_id = {
        group.id: group
        for model in group_result.scalars().all()
        for group in [ClientGroupRepository._to_entity(model)]
    }
    if len(groups_by_id) != len(ordered_group_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more selected passport groups were not found.",
        )
    groups = [groups_by_id[group_id] for group_id in ordered_group_ids]

    stmt = (
        select(PassportSubmissionModel)
        .join(
            ClientGroupModel,
            PassportSubmissionModel.group_id == ClientGroupModel.id,
        )
        .where(
            PassportSubmissionModel.group_id.in_(ordered_group_ids),
            PassportSubmissionModel.status.in_(_submitted_statuses()),
            operational_roster_member(),
        )
    )
    stmt = _apply_manager_visibility(stmt, current_user)
    result = await session.execute(stmt.limit(PASSPORT_COMBINED_EXPORT_MAX_ROWS + 1))
    submissions = [
        PassportSubmissionRepository._to_entity(model) for model in result.scalars().all()
    ]
    if len(submissions) > PASSPORT_COMBINED_EXPORT_MAX_ROWS:
        raise HTTPException(
            status_code=413,
            detail="Combined exports are limited to 1500 passengers. Select fewer groups.",
        )
    return groups, submissions


@router.post(
    "/groups/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export selected passport groups to Excel",
)
async def export_selected_groups(
    body: ExportSelectedGroupsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    groups, submissions = await _selected_groups_export_context(
        group_ids=body.group_ids,
        current_user=current_user,
        session=session,
    )

    match_rows_by_group = await _export_whatsapp_match_rows(
        session,
        submissions,
        groups=groups,
    )
    catalog = _combined_export_field_catalog(
        groups,
        match_rows_by_group,
        submissions,
    )
    catalog_by_key = {str(field["key"]): field for field in catalog}
    submitted_field_keys = list(dict.fromkeys(body.supplemental_fields))
    unknown_fields = [key for key in submitted_field_keys if key not in catalog_by_key]
    if unknown_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("One or more selected Excel fields are unavailable for the selected groups."),
        )
    submitted_field_key_set = set(submitted_field_keys)
    selected_fields = [field for field in catalog if str(field["key"]) in submitted_field_key_set]
    requested_field_keys = [str(field["key"]) for field in selected_fields]
    resolved_group_by = _resolve_export_group_by(
        body.group_by_field,
        requested_field_keys,
    )
    airport_enabled = any(_international_airport_is_enabled(group) for group in groups)
    if resolved_group_by == "international_airport" and not airport_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "International Airport grouping is available only when at "
                "least one selected group asks travellers for that field."
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

    pending_rows: list[dict[str, Any]] = []
    for group in groups:
        group_pending_rows = _pending_recipient_export_rows(
            group=group,
            rows=match_rows_by_group.get(group.id, []),
        )
        if group_pending_rows:
            _apply_pending_export_fields(
                group_pending_rows,
                match_rows_by_group.get(group.id, []),
                selected_fields,
            )
            pending_rows.extend(group_pending_rows)
    if not submissions and not pending_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No exportable passport submissions or pending recipients found",
        )

    if len(submissions) + len(pending_rows) > PASSPORT_COMBINED_EXPORT_MAX_ROWS:
        raise HTTPException(
            status_code=413,
            detail="Combined exports are limited to 1500 rows including pending recipients. Select fewer groups.",
        )

    content = await asyncio.to_thread(
        PassportExcelExporter().export_group,
        submissions,
        group_name="Selected Groups",
        group_details={group.id: _group_export_details(group) for group in groups},
        zone_names=_export_zone_names_from_match_rows(
            submissions,
            match_rows_by_group,
        ),
        additional_fields=[
            {"key": str(field["key"]), "label": str(field["label"])} for field in selected_fields
        ],
        additional_values=_export_additional_values(
            submissions,
            match_rows_by_group,
            selected_fields,
        ),
        whatsapp_contacts=_export_whatsapp_contacts(
            submissions,
            match_rows_by_group,
        ),
        group_by_field=resolved_group_by,
        pending_rows=pending_rows,
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="selected-groups-passports.xlsx"'},
    )
