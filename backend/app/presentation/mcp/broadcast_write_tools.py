"""Broadcast creation and edits share canonical persistence, never provider dispatch."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import FastAPI, HTTPException
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select

from app.application.mcp.change_context import require_change_actor
from app.application.mcp.credentials import utc
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.whatsapp_archive_policy import require_active_broadcast
from app.presentation.api.v1.routes.whatsapp_creation import create_new_broadcast
from app.presentation.api.v1.routes.whatsapp_groups_manage import update_broadcast_group
from app.presentation.api.v1.routes.whatsapp_recipients import add_validated_broadcast_recipients
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppRecipientInput,
    WhatsAppSupportContactInput,
)
from app.presentation.mcp.dashboard_edit_operations import row_snapshot
from app.presentation.mcp.dashboard_write_support import (
    MAX_RESULT_BYTES,
    public_failure,
    scoped_actor,
)
from app.presentation.mcp.invocation import invoke_operation


class Contact(WhatsAppRecipientInput):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, max_length=100)
    phone_number: str = Field(min_length=8, max_length=32)
    imported_fields: dict[str, str] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def bounded_fields(self) -> Self:
        if any(len(key) > 64 or len(value) > 500 for key, value in self.imported_fields.items()):
            raise ValueError("Contact fields exceed their limits")
        return self


class Support(WhatsAppSupportContactInput):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=8, max_length=32)


class BroadcastCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID
    name: str = Field(min_length=1, max_length=100)
    organizing_company_name: str | None = Field(default=None, max_length=100)
    contacts: list[Contact] = Field(min_length=1, max_length=500)
    support_contacts: list[Support] = Field(min_length=1, max_length=3)
    recipient_opt_in_confirmed: Literal[True]


class BroadcastEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID
    broadcast_id: UUID
    expected_updated_at: datetime
    name: str | None = Field(default=None, min_length=1, max_length=100)
    organizing_company_name: str | None = Field(default=None, min_length=1, max_length=100)
    support_contacts: list[Support] | None = Field(default=None, min_length=1, max_length=3)

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if (
            self.name is None
            and self.organizing_company_name is None
            and self.support_contacts is None
        ):
            raise ValueError("Provide at least one change")
        return self


class BroadcastContacts(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID
    broadcast_id: UUID
    expected_updated_at: datetime
    contacts: list[Contact] = Field(min_length=1, max_length=500)
    recipient_opt_in_confirmed: Literal[True]


BROADCAST_WRITE_MODELS: dict[str, type[BroadcastCreate] | type[BroadcastEdit] | type[BroadcastContacts]] = {
    "create_whatsapp_broadcast": BroadcastCreate,
    "update_broadcast_details": BroadcastEdit,
    "add_broadcast_contacts": BroadcastContacts,
}


def require_bounded_history(history: dict[str, Any]) -> None:
    if len(json.dumps(history, ensure_ascii=False).encode("utf-8")) > MAX_RESULT_BYTES:
        raise MCPOperationError("broadcast_source_limit")


async def broadcast_row(context: MCPDatabaseContext, agency_id: UUID, broadcast_id: UUID) -> WhatsAppBroadcastGroupModel:
    row = await context.session.scalar(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == broadcast_id,
            WhatsAppBroadcastGroupModel.agency_id == agency_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise MCPOperationError("broadcast_unavailable")
    try:
        require_active_broadcast(row)
    except HTTPException as exc:
        raise public_failure(exc) from exc
    return row


def broadcast_write_operation(name: str) -> MCPDatabaseOperation:
    if name not in BROADCAST_WRITE_MODELS:
        raise ValueError("Unsupported broadcast write")

    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        try:
            body = BROADCAST_WRITE_MODELS[name].model_validate(payload)
        except ValidationError as exc:
            raise MCPOperationError("invalid_broadcast_write") from exc
        actor = await require_change_actor(context, body.agency_id)
        history: dict[str, Any] = {}
        try:
            if isinstance(body, BroadcastCreate):
                row = await create_new_broadcast(
                    context.session,
                    agency_id=body.agency_id,
                    actor_id=actor.id,
                    name=body.name,
                    organizing_company_name=body.organizing_company_name,
                    contacts=list(body.contacts),
                    rejected_contacts=[],
                    support_contacts=list(body.support_contacts),
                    recipient_opt_in_confirmed=body.recipient_opt_in_confirmed,
                    declared_field_keys=[],
                )
            else:
                row = await broadcast_row(context, body.agency_id, body.broadcast_id)
                if utc(row.updated_at) != utc(body.expected_updated_at):
                    raise MCPOperationError("broadcast_revision_changed")
                recipients = list(
                    (
                        await context.session.scalars(
                            select(WhatsAppBroadcastRecipientModel)
                            .where(
                                WhatsAppBroadcastRecipientModel.broadcast_group_id == row.id,
                            )
                            .order_by(WhatsAppBroadcastRecipientModel.id)
                            .limit(1001)
                            .with_for_update()
                        )
                    ).all()
                )
                if len(recipients) > 1000:
                    raise MCPOperationError("broadcast_source_limit")
                history["group"] = row_snapshot(row)
                if isinstance(body, BroadcastEdit):
                    support = list(
                        (
                            await context.session.scalars(
                                select(WhatsAppBroadcastSupportContactModel)
                                .where(
                                    WhatsAppBroadcastSupportContactModel.broadcast_group_id
                                    == row.id,
                                )
                                .order_by(WhatsAppBroadcastSupportContactModel.id)
                                .limit(4)
                                .with_for_update()
                            )
                        ).all()
                    )
                    if len(support) > 3:
                        raise MCPOperationError("broadcast_source_limit")
                    history["support_contacts"] = [row_snapshot(item) for item in support]
                    require_bounded_history(history)
                    await update_broadcast_group(
                        row.id,
                        name=body.name,
                        organizing_company_name=body.organizing_company_name,
                        support_contacts_json=json.dumps(
                            [item.model_dump(mode="json") for item in body.support_contacts]
                        )
                        if body.support_contacts is not None
                        else None,
                        current_user=actor,
                        session=context.session,
                    )
                else:
                    history["recipients"] = [row_snapshot(item) for item in recipients]
                    require_bounded_history(history)
                    await add_validated_broadcast_recipients(
                        group_id=row.id,
                        contacts=list(body.contacts),
                        rejected_contacts=[],
                        declared_field_keys=[],
                        recipient_opt_in_confirmed=body.recipient_opt_in_confirmed,
                        current_user=actor,
                        session=context.session,
                    )
        except HTTPException as exc:
            raise public_failure(exc) from exc
        audit = await AuditLogRepository(context.session).record(
            action="mcp.broadcast_write",
            entity_type="whatsapp_broadcast",
            entity_id=str(row.id),
            agency_id=body.agency_id,
            user_id=actor.id,
            actor_email=actor.email,
            metadata={
                "workflow": name,
                "mcp_operation_id": str(context.operation_id),
                "retained_before": history,
            },
        )
        return MCPDatabaseResult(
            {
                "agency_id": str(row.agency_id),
                "broadcast_id": str(row.id),
                "updated_at": utc(row.updated_at).isoformat(),
                "business_audit_id": str(audit.id),
                "messages_sent": 0,
                "notice": "Broadcast details are saved. Sending requires a separate reviewed plan and final confirmation.",
            },
            created_entities=(
                MCPCreatedEntity("whatsapp_broadcast", str(row.id), f"/whatsapp/{row.id}"),
            )
            if name == "create_whatsapp_broadcast"
            else (),
        )

    async def authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        data = receipt["data"]
        await scoped_actor(context, UUID(data["agency_id"]))
        await broadcast_row(context, UUID(data["agency_id"]), UUID(data["broadcast_id"]))

    return MCPDatabaseOperation(
        MCPToolPolicy(name, MCPCapability.CHANGE, frozenset({"broadcast_edit_with_history"})),
        mutate,
        authorize_receipt,
    )


def register_broadcast_write_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    def register(name: str, model: type[BaseModel]) -> None:
        definition = broadcast_write_operation(name)
        app.state.mcp_operations[name] = definition

        async def execute(
            change: BaseModel, idempotency_key: Annotated[str, Field(min_length=16, max_length=256)]
        ) -> dict[str, Any]:
            return await invoke_operation(
                app,
                settings,
                definition,
                idempotency_key=idempotency_key,
                payload=change.model_dump(mode="json"),
            )

        execute.__name__ = name
        execute.__annotations__["change"] = model
        execute.__doc__ = "Save the user's explicitly chosen broadcast details/contacts using current dashboard rules. Clarify the exact agency, broadcast, support contacts and recipient opt-in. Inspect the current revision before editing. Existing contacts/history are retained. This never sends a message. Ask what content to send, prepare an exact audience/content preview, and obtain final confirmation using the separate send workflow. Reuse the same stable retry key and exact input after an uncertain response."
        server.tool(
            name=name,
            meta={"capability": "mcp:change"},
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )(execute)

    for name, model in BROADCAST_WRITE_MODELS.items():
        register(name, model)
