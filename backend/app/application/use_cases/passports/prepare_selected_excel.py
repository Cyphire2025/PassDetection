"""The website and MCP share combined-group workbook construction."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.passports.excel_snapshot import snapshot_digest
from app.application.use_cases.passports.prepare_group_excel import (
    ExcelPreparationError,
    PreparedGroupExcel,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission


@dataclass(frozen=True)
class SelectedExcelSupport:
    _export_group_details: Callable[..., Any]
    _export_whatsapp_match_rows: Callable[..., Any]
    _combined_export_field_catalog: Callable[..., Any]
    _resolve_export_group_by: Callable[..., Any]
    _international_airport_is_enabled: Callable[..., Any]
    _pending_recipient_export_rows: Callable[..., Any]
    _apply_pending_export_fields: Callable[..., Any]
    _group_export_details: Callable[..., Any]
    export_passport_ecr_results: Callable[..., Any]
    _export_zone_names_from_match_rows: Callable[..., Any]
    _export_additional_values: Callable[..., Any]
    _export_whatsapp_contacts: Callable[..., Any]


async def prepare_selected_groups_excel(
    session: AsyncSession,
    *,
    support: SelectedExcelSupport,
    groups: list[ClientGroup],
    submissions: list[PassportSubmission],
    agency_id: uuid.UUID,
    supplemental_fields: list[str],
    group_by_field: str | None,
    maximum_fields: int | None = None,
    maximum_snapshot_bytes: int | None = None,
) -> PreparedGroupExcel:
    match_rows_by_group = await support._export_whatsapp_match_rows(
        session,
        submissions,
        groups=groups,
    )
    catalog = support._combined_export_field_catalog(
        groups,
        match_rows_by_group,
        submissions,
    )
    if maximum_fields is not None and len(catalog) > maximum_fields:
        raise ExcelPreparationError(status_code=413, detail="Excel exceeds the field limit")
    catalog_by_key = {str(field["key"]): field for field in catalog}
    submitted_field_keys = list(dict.fromkeys(supplemental_fields))
    unknown_fields = [key for key in submitted_field_keys if key not in catalog_by_key]
    if unknown_fields:
        raise ExcelPreparationError(
            status_code=400,
            detail=("One or more selected Excel fields are unavailable for the selected groups."),
        )
    submitted_field_key_set = set(submitted_field_keys)
    selected_fields = [field for field in catalog if str(field["key"]) in submitted_field_key_set]
    requested_field_keys = [str(field["key"]) for field in selected_fields]
    resolved_group_by = support._resolve_export_group_by(
        group_by_field,
        requested_field_keys,
    )
    airport_enabled = any(support._international_airport_is_enabled(group) for group in groups)
    if resolved_group_by == "international_airport" and not airport_enabled:
        raise ExcelPreparationError(
            status_code=400,
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
        raise ExcelPreparationError(
            status_code=400,
            detail=(
                "The grouping field must be International Airport or an included WhatsApp field."
            ),
        )

    pending_rows: list[dict[str, Any]] = []
    for group in groups:
        group_pending_rows = support._pending_recipient_export_rows(
            group=group,
            rows=match_rows_by_group.get(group.id, []),
        )
        if group_pending_rows:
            support._apply_pending_export_fields(
                group_pending_rows,
                match_rows_by_group.get(group.id, []),
                selected_fields,
            )
            pending_rows.extend(group_pending_rows)
    if not submissions and not pending_rows:
        raise ExcelPreparationError(
            status_code=404,
            detail="No exportable passport submissions or pending recipients found",
        )

    if len(submissions) + len(pending_rows) > 1500:
        raise ExcelPreparationError(
            status_code=413,
            detail="Combined exports are limited to 1500 rows including pending recipients. Select fewer groups.",
        )

    group_details = {group.id: support._group_export_details(group) for group in groups}
    ecr_results = await support.export_passport_ecr_results(
        session,
        submissions,
        agency_id=agency_id,
        group_details=group_details,
    )
    render_arguments = dict(
        group_name="Selected Groups",
        group_details=group_details,
        ecr_results=ecr_results,
        zone_names=support._export_zone_names_from_match_rows(
            submissions,
            match_rows_by_group,
        ),
        additional_fields=[
            {"key": str(field["key"]), "label": str(field["label"])} for field in selected_fields
        ],
        additional_values=support._export_additional_values(
            submissions,
            match_rows_by_group,
            selected_fields,
        ),
        whatsapp_contacts=support._export_whatsapp_contacts(
            submissions,
            match_rows_by_group,
        ),
        group_by_field=resolved_group_by,
        pending_rows=pending_rows,
    )
    revision = snapshot_digest(
        {"groups": groups, "submissions": submissions, "render_arguments": render_arguments},
        maximum_bytes=maximum_snapshot_bytes,
    )
    return PreparedGroupExcel(submissions, render_arguments, {}, revision, catalog)


async def prepare_selected_passports_excel(
    session: AsyncSession,
    *,
    support: SelectedExcelSupport,
    submissions: list[PassportSubmission],
    agency_id: uuid.UUID,
    maximum_snapshot_bytes: int | None = None,
) -> PreparedGroupExcel:
    match_rows_by_group = await support._export_whatsapp_match_rows(session, submissions)
    group_details = await support._export_group_details(
        session,
        [submission.group_id for submission in submissions],
    )
    ecr_results = await support.export_passport_ecr_results(
        session,
        submissions,
        agency_id=agency_id,
        group_details=group_details,
    )
    render_arguments = dict(
        group_name="Selected Passports",
        group_details=group_details,
        ecr_results=ecr_results,
        zone_names=support._export_zone_names_from_match_rows(
            submissions,
            match_rows_by_group,
        ),
        whatsapp_contacts=support._export_whatsapp_contacts(
            submissions,
            match_rows_by_group,
        ),
    )
    revision = snapshot_digest(
        {"submissions": submissions, "render_arguments": render_arguments},
        maximum_bytes=maximum_snapshot_bytes,
    )
    return PreparedGroupExcel(submissions, render_arguments, {}, revision, [])
