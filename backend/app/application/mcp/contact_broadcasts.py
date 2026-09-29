"""Append-only Excel-to-new-broadcast operation with a reviewed preview fingerprint."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.application.dtos.whatsapp_contact_dtos import WhatsAppSupportContactInput
from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.contact_mapping import (
    ContactColumnMapping,
    ContactMappingSupport,
    MappedContacts,
    map_contacts,
)
from app.application.mcp.contact_uploads import MCPContactUploadService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_contact_import_models import MCPContactImportUploadModel
from app.infrastructure.database.models import WhatsAppBroadcastGroupModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


@dataclass(frozen=True)
class ContactBroadcastSupport:
    mapping: ContactMappingSupport
    validate: Callable[..., Any]
    create: Callable[..., Awaitable[WhatsAppBroadcastGroupModel]]


class ContactSupportInput(WhatsAppSupportContactInput):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ContactBroadcastDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    upload_id: str = Field(pattern=r"^gcmcp_contacts_[A-Za-z0-9_-]{64}$")
    agency_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    organizing_company_name: str = Field(min_length=1, max_length=100)
    support_contacts: list[ContactSupportInput] = Field(min_length=1, max_length=3)
    recipient_opt_in_confirmed: bool = Field(strict=True)
    column_mappings: list[ContactColumnMapping] = Field(min_length=1, max_length=50)


class ContactBroadcastCreation(ContactBroadcastDraft):
    preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def project_import(
    row: MCPContactImportUploadModel,
    draft: ContactBroadcastDraft,
    *,
    support: ContactBroadcastSupport,
) -> tuple[MappedContacts, dict[str, Any]]:
    if row.agency_id != draft.agency_id:
        raise MCPAuthError("access_denied", 403)
    mapped = map_contacts(
        row.workbook_snapshot,
        filename=row.filename,
        mappings=draft.column_mappings,
        support=support.mapping,
    )
    if mapped.contacts and not draft.recipient_opt_in_confirmed:
        raise MCPOperationError("contact_opt_in_required")
    _, _, _, normalized_support = support.validate(
        name=draft.name,
        organizing_company_name=draft.organizing_company_name,
        contacts=mapped.contacts,
        rejected_contacts=mapped.rejected,
        support_contacts=draft.support_contacts,
        recipient_opt_in_confirmed=draft.recipient_opt_in_confirmed,
    )
    command = draft.model_dump(mode="json", exclude={"preview_sha256"})
    preview = {
        "agency_id": str(row.agency_id),
        "name": draft.name,
        "organizing_company_name": draft.organizing_company_name,
        "support_contacts": [
            value.model_dump(mode="json") for value in normalized_support.values()
        ],
        "recipient_opt_in_confirmed": draft.recipient_opt_in_confirmed,
        "column_mappings": command["column_mappings"],
        "source_sha256": row.sha256,
        **mapped.preview(support.mapping),
    }
    fingerprint = {"schema_version": 1, "command": command, "preview": preview}
    preview["preview_sha256"] = hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    preview["source_retained"] = True
    preview["messages_queued"] = 0
    return mapped, preview


def contact_broadcast_operation(
    settings: Settings, support: ContactBroadcastSupport
) -> MCPDatabaseOperation:
    policy = MCPToolPolicy(
        "create_contact_broadcast",
        MCPCapability.CHANGE,
        frozenset({"create_broadcast", "import_contacts"}),
    )

    async def create(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        try:
            draft = ContactBroadcastCreation.model_validate(payload)
        except ValidationError as exc:
            raise MCPOperationError("invalid_contact_broadcast") from exc
        service = MCPContactUploadService(context.session, settings)
        try:
            row = await service.get(context.principal, draft.upload_id, lock=True)
        except ArtifactError as exc:
            raise MCPOperationError("contact_upload_unavailable") from exc
        if row.consumed_operation_id is not None:
            raise MCPOperationError("contact_upload_already_used")
        mapped, preview = project_import(row, draft, support=support)
        if not hmac.compare_digest(draft.preview_sha256, preview["preview_sha256"]):
            raise MCPOperationError("contact_preview_changed")
        group = await support.create(
            context.session,
            agency_id=row.agency_id,
            actor_id=context.principal.user_id,
            name=draft.name,
            organizing_company_name=draft.organizing_company_name,
            contacts=mapped.contacts,
            rejected_contacts=mapped.rejected,
            support_contacts=list(draft.support_contacts),
            recipient_opt_in_confirmed=draft.recipient_opt_in_confirmed,
            declared_field_keys=mapped.field_keys,
        )
        row.consumed_operation_id, row.broadcast_id, row.consumed_at = (
            context.operation_id,
            group.id,
            datetime.now(UTC),
        )
        audit = await AuditLogRepository(context.session).record(
            action="mcp.contact_broadcast_created",
            entity_type="whatsapp_broadcast_group",
            entity_id=str(group.id),
            agency_id=row.agency_id,
            user_id=context.principal.user_id,
            metadata={
                "operation_id": str(context.operation_id),
                "upload_id": str(row.id),
                "accepted_count": len(mapped.contacts),
                "rejected_count": len(mapped.rejected),
            },
        )
        return MCPDatabaseResult(
            {
                "broadcast_id": str(group.id),
                "agency_id": str(row.agency_id),
                "name": group.name,
                "accepted_count": len(mapped.contacts),
                "rejected_count": len(mapped.rejected),
                "rejected_counts": preview["rejected_counts"],
                "source_rows": mapped.source_rows,
                "preview_sha256": preview["preview_sha256"],
                "source_retained": True,
                "messages_queued": 0,
                "business_audit_id": str(audit.id),
            },
            created_entities=(
                MCPCreatedEntity("whatsapp_broadcast_group", str(group.id), "/whatsapp"),
            ),
        )

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        service = MCPContactUploadService(context.session, settings)
        await service.authority(context.principal)
        data = receipt["data"]
        agency_id, broadcast_id = uuid.UUID(data["agency_id"]), uuid.UUID(data["broadcast_id"])
        await service.agency(agency_id)
        group = await context.session.scalar(
            select(WhatsAppBroadcastGroupModel).where(
                WhatsAppBroadcastGroupModel.id == broadcast_id,
                WhatsAppBroadcastGroupModel.agency_id == agency_id,
                WhatsAppBroadcastGroupModel.created_by_user_id == context.principal.user_id,
            )
        )
        if group is None:
            raise MCPAuthError("access_denied", 403)

    return MCPDatabaseOperation(policy, create, authorize)
