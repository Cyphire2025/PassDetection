"""Canonical tracking filters and frozen workbook inputs shared by web and MCP."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.passports.prepare_group_excel import (
    ExcelPreparationError,
    ExcelPreparationSupport,
    PreparedGroupExcel,
    _canonical,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission

TrackingStatus = Literal[
    "all",
    "submitted",
    "not_submitted",
    "multiple_submissions",
    "needs_review",
    "unmatched_submission",
    "replacement",
    "rejected_upload",
]


@dataclass(frozen=True)
class TrackingExcelSupport:
    group: ExcelPreparationSupport
    tracking_rows: Callable[..., Any]
    select_payload: Callable[..., Any]


async def prepare_tracking_excel(
    session: AsyncSession,
    *,
    support: TrackingExcelSupport,
    group: ClientGroup,
    submissions: list[PassportSubmission],
    tracking_status: TrackingStatus,
    broadcast_id: uuid.UUID | None,
    maximum_fields: int | None = None,
    maximum_snapshot_bytes: int | None = None,
) -> PreparedGroupExcel:
    linked, rows = await support.tracking_rows(session, group=group, submissions=submissions)
    if not linked:
        raise ExcelPreparationError(
            status_code=409,
            detail="Link at least one WhatsApp broadcast before exporting tracking.",
        )
    if broadcast_id is not None and broadcast_id not in linked:
        raise ExcelPreparationError(
            status_code=400,
            detail="The selected WhatsApp broadcast is not linked to this client group.",
        )
    selected, selected_rows = support.select_payload(
        submissions, rows, tracking_status=tracking_status, broadcast_id=broadcast_id
    )
    common = support.group
    by_group = {group.id: selected_rows}
    catalog = common._export_field_catalog(group, selected_rows, selected)
    if maximum_fields is not None and len(catalog) > maximum_fields:
        raise ExcelPreparationError(status_code=413, detail="Tracking exceeds the field limit")
    fields = [field for field in catalog if field["selected_by_default"]]
    group_by = common._resolve_export_group_by(None, [str(field["key"]) for field in fields])
    pending = common._pending_recipient_export_rows(group=group, rows=selected_rows)
    if pending:
        common._apply_pending_export_fields(pending, selected_rows, fields)
    details = {group.id: common._group_export_details(group)}
    arguments = {
        "group_name": group.name,
        "group_details": details,
        "ecr_results": await common.export_passport_ecr_results(
            session, selected, agency_id=group.agency_id, group_details=details
        ),
        "zone_names": common._export_zone_names_from_match_rows(selected, by_group),
        "additional_fields": [
            {"key": str(field["key"]), "label": str(field["label"])} for field in fields
        ],
        "additional_values": common._export_additional_values(selected, by_group, fields),
        "whatsapp_contacts": common._export_whatsapp_contacts(selected, by_group),
        "group_by_field": group_by,
        "pending_rows": pending,
    }
    # Include the whole comparison source, not just currently selected rows: a
    # changed resolution can move a traveller into or out of a status filter.
    snapshot = _canonical(
        {
            "group": group,
            "submissions": submissions,
            "linked": linked,
            "rows": rows,
            "status": tracking_status,
            "broadcast_id": broadcast_id,
            "arguments": arguments,
        }
    )
    digest, byte_count = hashlib.sha256(), 0
    for part in json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False).iterencode(
        snapshot
    ):
        encoded = part.encode()
        byte_count += len(encoded)
        if maximum_snapshot_bytes is not None and byte_count > maximum_snapshot_bytes:
            raise ExcelPreparationError(
                status_code=413, detail="Tracking exceeds the snapshot size limit"
            )
        digest.update(encoded)
    return PreparedGroupExcel(selected, arguments, {}, digest.hexdigest(), catalog)
