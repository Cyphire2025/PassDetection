"""Shared group Excel preparation; transports provide fixed application dependencies.

No workbook, history or storage is written during preparation. The same frozen
render inputs feed the web download and MCP revision fence.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.passports.excel_snapshot import snapshot_digest
from app.domain.entities.entities import ClientGroup, PassportSubmission, User
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.export.passport_excel_exporter import PassportExcelExporter
from app.infrastructure.repositories.passport_export_history_repository import PassportExportMode


class ExcelPreparationError(ValueError):
    def __init__(self, *, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def _canonical(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical(asdict(value))
    if isinstance(value, dict):
        return {str(key): _canonical(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(child) for child in value]
    if isinstance(value, (date, datetime, uuid.UUID)):
        return str(value)
    if isinstance(value, Enum):
        return _canonical(value.value)
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError("Unsupported export snapshot value")


@dataclass(frozen=True)
class ExcelPreparationSupport:
    _current_group_export_submissions: Callable[..., Any]
    _resolve_group_export_payload: Callable[..., Any]
    _owner_scope_for: Callable[..., Any]
    _export_whatsapp_match_rows: Callable[..., Any]
    _export_field_catalog: Callable[..., Any]
    _export_agency_match_field_catalog: Callable[..., Any]
    _agency_match_export_field: Callable[..., Any]
    _resolve_export_group_by: Callable[..., Any]
    _international_airport_is_enabled: Callable[..., Any]
    _export_agency_matches: Callable[..., Any]
    _AgencyExportMatches: Callable[..., Any]
    _export_effective_whatsapp_matches: Callable[..., Any]
    _pending_recipient_export_rows: Callable[..., Any]
    _apply_pending_export_fields: Callable[..., Any]
    _export_additional_values: Callable[..., Any]
    _export_whatsapp_contacts: Callable[..., Any]
    _export_zone_names_from_match_rows: Callable[..., Any]
    _apply_agency_export_matches: Callable[..., Any]
    _group_export_details: Callable[..., Any]
    export_passport_ecr_results: Callable[..., Any]
    _export_people_snapshot: Callable[..., Any]


@dataclass(frozen=True)
class PreparedGroupExcel:
    submissions: list[PassportSubmission]
    render_arguments: dict[str, Any]
    history_fields: dict[str, Any]
    revision: str
    field_catalog: list[dict[str, Any]]

    async def render(self, **limits: Any) -> bytes:
        results = await run_bounded_storage_operations(
            [
                lambda: asyncio.to_thread(
                    PassportExcelExporter().export_group,
                    self.submissions,
                    **self.render_arguments,
                    **limits,
                )
            ],
            concurrency=1,
        )
        return results[0]


async def prepare_group_excel(
    session: AsyncSession,
    *,
    support: ExcelPreparationSupport,
    current_user: User,
    agency_id: uuid.UUID,
    group: ClientGroup,
    export_mode: PassportExportMode = "all",
    baseline_export_id: uuid.UUID | None = None,
    supplemental_fields: str | None = None,
    group_by_field: str | None = None,
    agency_match_field: str | None = None,
    maximum_fields: int | None = None,
    maximum_snapshot_bytes: int | None = None,
) -> PreparedGroupExcel:
    if export_mode not in {"all", "incremental"}:
        raise ExcelPreparationError(status_code=422, detail="Unsupported export mode")
    group_id = group.id
    current_submissions = await support._current_group_export_submissions(
        session,
        group_id=group_id,
        agency_id=agency_id,
        current_user=current_user,
    )
    submissions, baseline = await support._resolve_group_export_payload(
        session,
        group_id=group_id,
        agency_id=agency_id,
        export_kind="passport_excel",
        export_mode=export_mode,
        baseline_export_id=baseline_export_id,
        submissions=current_submissions,
        created_by_user_id=support._owner_scope_for(current_user),
    )
    match_rows_by_group = await support._export_whatsapp_match_rows(
        session,
        current_submissions,
        groups=[group],
    )
    catalog = support._export_field_catalog(
        group,
        match_rows_by_group.get(group.id, []),
        current_submissions,
    )
    if maximum_fields is not None and len(catalog) > maximum_fields:
        raise ExcelPreparationError(status_code=413, detail="Excel exceeds the field limit")
    catalog_by_key = {str(field["key"]): field for field in catalog}
    requested_field_keys = (
        list(dict.fromkeys(key.strip() for key in supplemental_fields.split(",") if key.strip()))
        if supplemental_fields is not None
        else [str(field["key"]) for field in catalog if field["selected_by_default"]]
    )
    unknown_fields = [key for key in requested_field_keys if key not in catalog_by_key]
    if unknown_fields:
        raise ExcelPreparationError(
            status_code=400,
            detail="One or more selected Excel fields are unavailable for this group.",
        )
    resolved_agency_match_field = (
        agency_match_field.strip() if agency_match_field and agency_match_field.strip() else None
    )
    agency_match_option: dict[str, str | bool] | None = None
    if resolved_agency_match_field:
        if not group.agency_dealership_name_enabled:
            raise ExcelPreparationError(
                status_code=400,
                detail=(
                    "Agency matching is available only when Agency/Dealership "
                    "Name is enabled for the group."
                ),
            )
        agency_match_catalog = support._export_agency_match_field_catalog(
            group,
            match_rows_by_group.get(group.id, []),
        )
        agency_match_options = {str(field["key"]): field for field in agency_match_catalog}
        agency_match_option = agency_match_options.get(resolved_agency_match_field)
        if agency_match_option is None:
            raise ExcelPreparationError(
                status_code=400,
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
        [support._agency_match_export_field(agency_match_option), *selected_fields]
        if agency_match_option is not None
        else selected_fields
    )
    resolved_group_by = support._resolve_export_group_by(
        group_by_field,
        requested_field_keys,
    )
    if resolved_group_by == resolved_agency_match_field:
        resolved_group_by = None
    if (
        resolved_group_by == "international_airport"
        and not support._international_airport_is_enabled(group)
    ):
        raise ExcelPreparationError(
            status_code=400,
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
        raise ExcelPreparationError(
            status_code=400,
            detail=(
                "The grouping field must be International Airport or an included WhatsApp field."
            ),
        )
    agency_matches = (
        support._export_agency_matches(
            submissions,
            match_rows_by_group,
            resolved_agency_match_field,
        )
        if resolved_agency_match_field
        else support._AgencyExportMatches({}, frozenset())
    )
    effective_matches = (
        support._export_effective_whatsapp_matches(
            agency_matches,
            match_rows_by_group,
        )
        if resolved_agency_match_field
        else agency_matches
    )
    pending_rows = (
        support._pending_recipient_export_rows(
            group=group,
            rows=match_rows_by_group.get(group.id, []),
            excluded_recipient_ids=effective_matches.matched_recipient_ids,
            include_name_history=bool(resolved_agency_match_field),
        )
        if export_mode == "all"
        else []
    )
    if pending_rows:
        support._apply_pending_export_fields(
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
        additional_values = support._export_additional_values(
            submissions,
            match_rows_by_group,
            selected_fields,
        )
        whatsapp_contacts = support._export_whatsapp_contacts(
            submissions,
            match_rows_by_group,
        )
        zone_names = support._export_zone_names_from_match_rows(
            submissions,
            match_rows_by_group,
        )
    previous_names = (
        support._apply_agency_export_matches(
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
    group_details = {group.id: support._group_export_details(group)}
    ecr_results = await support.export_passport_ecr_results(
        session,
        submissions,
        agency_id=agency_id,
        group_details=group_details,
    )
    render_arguments = dict(
        group_name=group.name,
        group_details=group_details,
        ecr_results=ecr_results,
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
    history_fields = dict(
        group_id=group_id,
        agency_id=agency_id,
        export_kind="passport_excel",
        export_mode=export_mode,
        baseline_export_id=baseline.id if baseline else None,
        snapshot_submission_ids=[submission.id for submission in current_submissions],
        exported_submission_ids=[submission.id for submission in submissions],
        exported_people_snapshot=support._export_people_snapshot(submissions),
        pending_recipient_count=len(pending_rows),
        artifact_metadata={
            "supplemental_fields": requested_field_keys,
            "group_by_field": resolved_group_by,
            "agency_match_field": resolved_agency_match_field,
            "agency_matched_submission_count": len(agency_matches.rows_by_submission),
        },
        created_by_user_id=current_user.id,
        actor_email=current_user.email,
    )
    revision = snapshot_digest(
        {
            "group": group,
            "current_submissions": current_submissions,
            "render_arguments": render_arguments,
            "history_fields": history_fields,
        },
        maximum_bytes=maximum_snapshot_bytes,
    )
    return PreparedGroupExcel(submissions, render_arguments, history_fields, revision, catalog)
