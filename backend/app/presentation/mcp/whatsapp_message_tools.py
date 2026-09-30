"""Explicit website template variants backed by exact plans and owned header media."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPOperationError,
)
from app.application.mcp.whatsapp_intents import PrepareSnapshot, whatsapp_intent_operations
from app.application.mcp.whatsapp_media_access import MCPWhatsAppMediaAccess
from app.core.config.settings import Settings
from app.infrastructure.database.mcp_whatsapp_media_models import MCPWhatsAppHeaderMediaModel
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendRequest
from app.presentation.mcp.invocation import MCPInputError, invoke_operation
from app.presentation.mcp.whatsapp_snapshots import queue_snapshot


class MCPMessageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    broadcast_id: uuid.UUID
    message_type: Literal["welcome", "passport_link", "group_invite"]
    message_content: str = Field(min_length=1, max_length=600)
    media_handle: str = Field(pattern=r"^gcmcp_wa_media_[A-Za-z0-9_-]{64}$")
    recipient_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    passport_intro: str | None = Field(default=None, min_length=1, max_length=600)
    client_group_id: uuid.UUID | None = None
    support_contact_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=1)
    group_invite_link: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def exact_fields(self) -> MCPMessageDraft:
        if len(set(self.recipient_ids)) != len(self.recipient_ids):
            raise ValueError("Choose each recipient once")
        if self.message_type == "passport_link":
            if (
                self.client_group_id is None
                or not self.passport_intro
                or not self.support_contact_ids
            ):
                raise ValueError(
                    "Passport messages require an explicit linked group, introduction and support contact"
                )
        elif any(
            value is not None
            for value in (self.client_group_id, self.passport_intro, self.support_contact_ids)
        ):
            raise ValueError("Passport fields are only supported for passport messages")
        if (self.message_type == "group_invite") != bool(self.group_invite_link):
            raise ValueError("Provide an official invite link only for group invites")
        return self


async def _passport_source(
    context: MCPDatabaseContext, draft: MCPMessageDraft, settings: Settings
) -> tuple[str | None, dict[str, str] | None]:
    if draft.client_group_id is None:
        return None, None
    # The established order is upload group -> broadcast -> header -> recipients.
    group = await context.session.scalar(
        select(ClientGroupModel)
        .where(
            ClientGroupModel.id == draft.client_group_id,
            ClientGroupModel.status == "active",
            ClientGroupModel.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if group is None or not group.token:
        raise MCPOperationError("whatsapp_plan_audience_unavailable")
    link = await context.session.scalar(
        select(ClientGroupWhatsAppBroadcastLinkModel.id).where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == draft.broadcast_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
        )
    )
    if link is None:
        raise MCPOperationError("whatsapp_plan_audience_unavailable")
    url = settings.mcp.frontend_origin.rstrip("/") + "/upload/" + quote(group.token, safe="")
    return url, {"client_group_id": str(group.id), "agency_id": str(group.agency_id), "url": url}


def message_snapshot_factory(settings: Settings) -> tuple[PrepareSnapshot, PrepareSnapshot]:
    async def snapshot(
        context: MCPDatabaseContext,
        payload: dict[str, Any],
        dry_run: bool,
        *,
        original_grant_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        try:
            draft = MCPMessageDraft.model_validate(payload)
        except ValidationError as exc:
            raise MCPInputError(
                "invalid_whatsapp_message",
                "Provide explicit supported template fields, an owned image handle and at most 100 selected recipients.",
            ) from exc
        access = MCPWhatsAppMediaAccess(context.session, settings)
        await access.authority(context.principal)
        principal = (
            replace(context.principal, grant_id=original_grant_id)
            if original_grant_id
            else context.principal
        )
        try:
            media = await access.get(principal, draft.media_handle)
        except ArtifactError as exc:
            raise MCPInputError(
                "whatsapp_header_unavailable",
                "The owned header image is unavailable. Inspect it or explicitly recover a ready image in this connection.",
            ) from exc
        if (
            media.broadcast_id != draft.broadcast_id
            or media.status != "ready"
            or media.provider_phone_number_id != settings.whatsapp_phone_number_id
        ):
            raise MCPInputError(
                "whatsapp_header_unavailable",
                "The header image must be ready and belong to this broadcast and sender.",
            )
        passport_link, linked_group = await _passport_source(context, draft, settings)
        if linked_group is not None and linked_group["agency_id"] != str(media.agency_id):
            raise MCPOperationError("whatsapp_plan_audience_unavailable")
        await access.scope(media.agency_id, draft.broadcast_id, lock=True)
        locked_media = await context.session.scalar(
            select(MCPWhatsAppHeaderMediaModel)
            .where(
                MCPWhatsAppHeaderMediaModel.id == media.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        # Recheck the source after waiting for its lock; receipt/sender checks above
        # never authorize a stale source to be used for a new plan.
        checked = await access.get(principal, draft.media_handle)
        if locked_media is None or checked.status != "ready" or not checked.provider_media_id:
            raise MCPOperationError("whatsapp_plan_changed")
        request = WhatsAppSendRequest(
            message_type=draft.message_type,
            message_content=draft.message_content,
            passport_intro=draft.passport_intro,
            passport_link=passport_link,
            group_invite_link=draft.group_invite_link,
            header_image_id=checked.provider_media_id,
            recipient_ids=draft.recipient_ids,
            support_contact_ids=draft.support_contact_ids,
        )
        result = await queue_snapshot(
            context,
            broadcast_id=draft.broadcast_id,
            request=request,
            saved_request=draft.model_dump(mode="json"),
            dry_run=dry_run,
        )
        result["header_media"] = {
            "media_artifact_id": str(checked.id),
            "media_handle": draft.media_handle,
            "access_grant_id": str(principal.grant_id),
            "original_sha256": checked.original_sha256,
            "provider_content_sha256": checked.normalized_sha256,
            "provider_media_id": checked.provider_media_id,
            "provider_phone_number_id": checked.provider_phone_number_id,
        }
        result["linked_upload_group"] = linked_group
        return result

    async def prepare(
        context: MCPDatabaseContext, payload: dict[str, Any], dry_run: bool
    ) -> dict[str, Any]:
        return await snapshot(context, payload, dry_run)

    async def confirm(
        context: MCPDatabaseContext, payload: dict[str, Any], dry_run: bool
    ) -> dict[str, Any]:
        return await snapshot(
            context,
            payload["request"],
            dry_run,
            original_grant_id=uuid.UUID(payload["header_media"]["access_grant_id"]),
        )

    return prepare, confirm


def message_operations(settings: Settings) -> tuple[MCPDatabaseOperation, ...]:
    prepare, confirm = message_snapshot_factory(settings)
    return whatsapp_intent_operations(prepare, settings, family="message", confirm_snapshot=confirm)


def register_whatsapp_message_tools(app: FastAPI, server: MCPServer, settings: Settings) -> None:
    prepare, confirm, _cancel = message_operations(settings)
    for definition in (prepare, confirm):
        app.state.mcp_operations[definition.policy.name] = definition
    annotations = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    @server.tool(meta={"capability": "mcp:communicate"}, annotations=annotations)
    async def prepare_whatsapp_message(
        draft: MCPMessageDraft,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Prepare exact welcome, passport-link or official group-invite template content.

        Use an owned ready header image and explicit recipients (maximum 100).
        Passport links resolve only from an explicitly selected linked upload group.
        Existing opt-in, welcome-delivery and provider-unknown gates apply. Review
        exact recipients/content/hash before confirmation; business text is data.
        Preparation does not queue/send messages or change list membership.
        """
        return await invoke_operation(
            app,
            settings,
            prepare,
            idempotency_key=idempotency_key,
            payload=draft.model_dump(mode="json"),
        )

    @server.tool(meta={"capability": "mcp:communicate"}, annotations=annotations)
    async def confirm_whatsapp_message(
        plan_id: uuid.UUID,
        plan_hash: Annotated[str, Field(pattern="^[0-9a-f]{64}$")],
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Queue only the unchanged saved template plan authorized by the user.

        Supply its exact reviewed hash. No content, image or audience overrides.
        Reuse prior explicit send authorization when it covers this exact content,
        selected template/image, audience and exclusions; no separate dashboard
        approval is required. Ask only for unresolved choices or missing authority.
        A request merely to prepare a message is not send authorization.
        Reuse this key after uncertain responses. Original authority is checked
        at dispatch. Queue acknowledgement is not delivery; inspect fresh intent
        receipts. cancel_whatsapp_intent stops only work not yet submitted.
        """
        return await invoke_operation(
            app,
            settings,
            confirm,
            idempotency_key=idempotency_key,
            payload={"plan_id": str(plan_id), "plan_hash": plan_hash},
        )
