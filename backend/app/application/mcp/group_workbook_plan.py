"""Canonical identity resolution and bounded current-roster preview fingerprints."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import load_only

from app.application.mcp.change_context import require_change_actor, require_change_group
from app.application.mcp.credentials import utc
from app.application.mcp.operations import MCPDatabaseContext, MCPOperationError
from app.domain.entities.entities import ClientGroup, User
from app.infrastructure.database.mcp_contact_import_models import MCPContactImportUploadModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_native_transfer_models import MCPNativeTransferModel
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.imports.passport_excel_importer import ImportedPassportRow

CHECKPOINT_KEY = "mcp_group_import_v1"
MAX_EXISTING_ROWS = 5000
MAX_EXISTING_JSON_BYTES = 16 * 1024 * 1024
MAX_PARSED_BYTES = 4 * 1024 * 1024
FIELDS = (
    "id",
    "agency_id",
    "group_id",
    "client_name",
    "client_email",
    "client_phone",
    "image_s3_key",
    "departure_city",
    "nearest_domestic_airport",
    "confirmed_fields",
    "extracted_fields",
    "staff_metadata",
    "confidence_score",
    "overall_confidence",
    "extraction_conflicts",
    "client_reviewed_at",
    "created_at",
    "updated_at",
    "status",
)
JSON_FIELDS = (
    "confirmed_fields",
    "extracted_fields",
    "staff_metadata",
    "confidence_score",
    "extraction_conflicts",
)


@dataclass(frozen=True, slots=True)
class GroupWorkbookSupport:
    indexes: Callable[[list[PassportSubmissionModel]], Any]
    resolve: Callable[[ImportedPassportRow, Any], PassportSubmissionModel | None]
    deduplicate: Callable[[list[ImportedPassportRow]], list[ImportedPassportRow]]
    apply: Callable[..., None]
    locked_scope: Callable[..., Awaitable[tuple[User, ClientGroup]]]
    conflict_type: type[ValueError]


class GroupWorkbookDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload_id: str = Field(pattern=r"^gcmcp_contacts_[A-Za-z0-9_-]{64}$")
    agency_id: uuid.UUID
    group_id: uuid.UUID
    source_sha256: str = Field(
        pattern=r"^[a-f0-9]{64}$",
        description="Exact original workbook SHA-256 from upload metadata.",
    )


class GroupWorkbookImport(GroupWorkbookDraft):
    preview_sha256: str = Field(
        pattern=r"^[a-f0-9]{64}$",
        description="Fresh unchanged canonical import preview fingerprint.",
    )


def encoded(value: Any) -> bytes:
    def convert(item: Any) -> str:
        if isinstance(item, datetime):
            return utc(item).isoformat()
        if isinstance(item, date):
            return item.isoformat()
        if isinstance(item, uuid.UUID):
            return str(item)
        raise TypeError("Unsupported checkpoint value")

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=convert,
    ).encode()


def parsed_checkpoint(
    rows: list[ImportedPassportRow], source_count: int, source_sha256: str
) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "source_sha256": source_sha256,
        "source_count": source_count,
        "rows": [asdict(row) for row in rows],
    }
    if not rows or len(rows) > 2000 or len(encoded(body)) > MAX_PARSED_BYTES:
        raise MCPOperationError("group_workbook_capacity_exceeded")
    return body


def checkpoint_rows(checkpoint: Any, source_sha256: str) -> list[ImportedPassportRow]:
    if type(checkpoint) is not dict or set(checkpoint) != {
        "schema_version",
        "source_sha256",
        "source_count",
        "rows",
    }:
        raise MCPOperationError("group_workbook_preview_required")
    if (
        type(checkpoint["schema_version"]) is not int
        or checkpoint["schema_version"] != 1
        or checkpoint["source_sha256"] != source_sha256
    ):
        raise MCPOperationError("group_workbook_source_changed")
    rows = checkpoint["rows"]
    if (
        type(rows) is not list
        or not rows
        or len(rows) > 2000
        or type(checkpoint["source_count"]) is not int
        or not len(rows) <= checkpoint["source_count"] <= 2000
        or len(encoded(checkpoint)) > MAX_PARSED_BYTES
    ):
        raise MCPOperationError("group_workbook_checkpoint_unavailable")
    try:
        result = [ImportedPassportRow(**row) for row in rows]
        for row in result:
            if (
                type(row.row_number) is not int
                or not 1 <= row.row_number <= 2000
                or not isinstance(row.worksheet_name, str)
                or not row.worksheet_name
                or not isinstance(row.client_name, str)
                or not 1 <= len(row.client_name) <= 255
            ):
                raise ValueError()
            if any(
                type(values) is not dict
                or any(
                    type(key) is not str or type(value) is not str for key, value in values.items()
                )
                for values in (row.confirmed_fields, row.staff_metadata)
            ):
                raise ValueError()
        return result
    except (ValueError, TypeError) as exc:
        raise MCPOperationError("group_workbook_checkpoint_unavailable") from exc


async def group_scope(
    context: MCPDatabaseContext,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    support: GroupWorkbookSupport,
) -> tuple[User, ClientGroupModel]:
    actor = await require_change_actor(context, agency_id)
    group = await require_change_group(context, actor, group_id, agency_id, exclusive=True)
    # This is the same locked own-agency identity/export guard used by the
    # website importer, without its route-level transaction management.
    actor, _ = await support.locked_scope(
        context.session,
        group_id=group_id,
        expected_agency_id=agency_id,
        user_id=context.principal.user_id,
        current_user=actor,
    )
    return actor, group


async def require_native_source(
    context: MCPDatabaseContext, row: MCPContactImportUploadModel, group_id: uuid.UUID
) -> None:
    ticket = MCPNativeTransferModel
    match = await context.session.scalar(
        select(ticket.id)
        .join(MCPGrantModel, MCPGrantModel.id == ticket.original_grant_id)
        .where(
            ticket.workbook_id == row.id,
            ticket.original_grant_id == context.principal.grant_id,
            ticket.user_id == context.principal.user_id,
            ticket.security_version == MCPGrantModel.security_version,
            ticket.kind == "upload_workbook",
            ticket.purpose == "group_workbook",
            ticket.status == "completed",
            ticket.completed_at.is_not(None),
            ticket.agency_id == row.agency_id,
            ticket.group_id == group_id,
            ticket.sha256 == row.sha256,
            ticket.byte_size == row.byte_size,
            ticket.media_type == row.media_type,
        )
        .with_for_update(read=True)
        .limit(1)
    )
    if match is None:
        raise MCPOperationError("native_group_workbook_required")


async def existing_roster(
    context: MCPDatabaseContext, agency_id: uuid.UUID, group_id: uuid.UUID, *, mutate: bool
) -> list[PassportSubmissionModel]:
    model = PassportSubmissionModel
    where = (model.agency_id == agency_id, model.group_id == group_id)
    sizes = [
        func.coalesce(func.length(cast(getattr(model, name), String)), 0) for name in JSON_FIELDS
    ]
    count, length = (
        await context.session.execute(
            select(func.count(), func.coalesce(func.sum(sum(sizes)), 0))
            .select_from(model)
            .where(*where)
        )
    ).one()
    if count > MAX_EXISTING_ROWS or length * 4 > MAX_EXISTING_JSON_BYTES:
        raise MCPOperationError("group_workbook_existing_roster_too_large")
    return list(
        (
            await context.session.scalars(
                select(model)
                .where(*where)
                .options(load_only(*(getattr(model, name) for name in FIELDS)))
                .order_by(model.id)
                .limit(MAX_EXISTING_ROWS + 1)
                .with_for_update(read=not mutate)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


def resolve_rows(
    rows: list[ImportedPassportRow],
    existing: list[PassportSubmissionModel],
    support: GroupWorkbookSupport,
) -> list[tuple[ImportedPassportRow, PassportSubmissionModel | None]]:
    try:
        indexes = support.indexes(existing)
        resolved = [(row, support.resolve(row, indexes)) for row in rows]
        identifiers = [item.id for _, item in resolved if item is not None]
        if len(set(identifiers)) != len(identifiers):
            raise support.conflict_type("Multiple source rows resolve to one passenger")
        return resolved
    except support.conflict_type as exc:
        raise MCPOperationError("group_workbook_identity_conflict") from exc


async def import_preview(
    context: MCPDatabaseContext,
    draft: GroupWorkbookDraft,
    checkpoint: dict[str, Any],
    *,
    support: GroupWorkbookSupport,
    mutate: bool = False,
) -> tuple[
    User,
    ClientGroupModel,
    list[tuple[ImportedPassportRow, PassportSubmissionModel | None]],
    dict[str, Any],
]:
    actor, group = await group_scope(context, draft.agency_id, draft.group_id, support)
    rows = checkpoint_rows(checkpoint, draft.source_sha256)
    existing = await existing_roster(context, draft.agency_id, draft.group_id, mutate=mutate)
    resolved = resolve_rows(rows, existing, support)
    revision = {
        "group": {
            "id": group.id,
            "agency_id": group.agency_id,
            "roster_revision": group.roster_revision,
            "status": group.status,
            "import_only": group.import_only,
            "name": group.name,
            "destination": group.destination,
            "travel_date": group.travel_date,
            "return_date": group.return_date,
            "timezone": group.timezone,
        },
        "existing": [{name: getattr(row, name) for name in FIELDS} for row in existing],
    }
    fingerprint = {
        "schema_version": 1,
        "command": draft.model_dump(mode="json", exclude={"preview_sha256"}),
        "parsed": checkpoint,
        "current_roster": revision,
    }
    updated = sum(item is not None for _, item in resolved)
    result = {
        "agency_id": str(group.agency_id),
        "group_id": str(group.id),
        "group_roster_revision": group.roster_revision,
        "source_sha256": draft.source_sha256,
        "source_rows": checkpoint["source_count"],
        "imported_count": len(rows) - updated,
        "updated_count": updated,
        "skipped_count": checkpoint["source_count"] - len(rows),
        "preview_sha256": hashlib.sha256(encoded(fingerprint)).hexdigest(),
        "source_retained": True,
        "business_import": "not_started",
        "content_trust": "untrusted_business_data",
        "sample": [
            {
                "source_sheet": row.worksheet_name,
                "row_number": row.row_number,
                "action": "update" if item else "create",
                "existing_passenger_id": str(item.id) if item else None,
                "passenger_name_preview": row.client_name[:120],
            }
            for row, item in resolved[:10]
        ],
        "notice": "Canonical identity matching and field merging; prior images, status and attendance are retained. Source-linked contact and mobile journals follow canonical profile changes; no messages are sent.",
    }
    return actor, group, resolved, result
