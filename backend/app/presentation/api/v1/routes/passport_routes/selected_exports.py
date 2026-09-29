"""Passport selected exports: focused workflow boundary."""

from __future__ import annotations

import io
import uuid
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.excel_export_options import (
    ExcelOptionsSupport,
    project_excel_export_options,
)
from app.application.use_cases.passports.prepare_group_excel import ExcelPreparationError
from app.application.use_cases.passports.prepare_selected_excel import (
    SelectedExcelSupport,
    prepare_selected_groups_excel,
    prepare_selected_passports_excel,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission, User, UserRole
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.passport_excel_exporter import (
    PassportExcelExporter as PassportExcelExporter,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.response_contracts import XLSX, binary_responses
from app.presentation.api.v1.schemas.passport_schemas import (
    ExportSelectedGroupsRequest,
    ExportSelectedPassportsRequest,
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
from .ecr_export_support import export_passport_ecr_results
from .excel_exports import export_options_support
from .export_context import _resolve_export_group_by
from .response_support import _apply_manager_visibility, _submitted_statuses

router = APIRouter()

def selected_excel_support() -> SelectedExcelSupport:
    """Fixed dependencies; request data can only select validated export options."""
    return SelectedExcelSupport(
        _export_group_details=_export_group_details,
        _export_whatsapp_match_rows=_export_whatsapp_match_rows,
        _combined_export_field_catalog=_combined_export_field_catalog,
        _resolve_export_group_by=_resolve_export_group_by,
        _international_airport_is_enabled=_international_airport_is_enabled,
        _pending_recipient_export_rows=_pending_recipient_export_rows,
        _apply_pending_export_fields=_apply_pending_export_fields,
        _group_export_details=_group_export_details,
        export_passport_ecr_results=export_passport_ecr_results,
        _export_zone_names_from_match_rows=_export_zone_names_from_match_rows,
        _export_additional_values=_export_additional_values,
        _export_whatsapp_contacts=_export_whatsapp_contacts,
    )



@router.post(
    "/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export selected passport submissions to Excel",
response_class=Response, responses=binary_responses(XLSX))
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

    prepared = await prepare_selected_passports_excel(
        session, support=selected_excel_support(), submissions=submissions,
        agency_id=current_user.agency_id,
    )
    content = await prepared.render()
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
    base = export_options_support()
    options = project_excel_export_options(
        groups=groups, submissions=submissions, rows_by_group=match_rows_by_group,
        selection="selected_groups",
        support=ExcelOptionsSupport(base.group_catalog, _combined_export_field_catalog,
                                    base.agency_match_catalog, _international_airport_is_enabled),
    )
    return PassportSelectedGroupsExportFieldOptionsResponse(
        group_ids=[group.id for group in groups],
        **options.model_dump(exclude={"agency_match_enabled", "agency_match_fields"}),
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
response_class=Response, responses=binary_responses(XLSX))
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

    try:
        prepared = await prepare_selected_groups_excel(
            session, support=selected_excel_support(), groups=groups, submissions=submissions,
            agency_id=cast(uuid.UUID, current_user.agency_id),
            supplemental_fields=body.supplemental_fields, group_by_field=body.group_by_field,
        )
    except ExcelPreparationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    content = await prepared.render()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="selected-groups-passports.xlsx"'},
    )
