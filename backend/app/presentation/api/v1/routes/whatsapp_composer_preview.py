"""Resolve the current preview audience and its selected immutable snapshot."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_block_message,
    group_invite_blocking_statuses,
)
from app.presentation.api.v1.routes.whatsapp_archive_policy import require_active_broadcast
from app.presentation.api.v1.routes.whatsapp_preview_recipient import select_preview_recipient
from app.presentation.api.v1.routes.whatsapp_reminder_audience import (
    ReminderAudienceResolution,
    resolve_reminder_audience,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES,
    _agency_filter,
    _as_message_type,
    _group_recipients,
    _latest_composer_snapshot,
    _select_group_recipients,
    _WhatsAppComposerSnapshot,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppPreviewRequest


@dataclass(frozen=True)
class PreviewSelection:
    group: WhatsAppBroadcastGroupModel
    source_recipients: list[WhatsAppBroadcastRecipientModel]
    audience_resolution: ReminderAudienceResolution
    recipients: list[WhatsAppBroadcastRecipientModel]
    recipient: WhatsAppBroadcastRecipientModel
    message_type: WhatsAppMessageType


@dataclass(frozen=True)
class PreviewSavedSnapshot:
    snapshot: _WhatsAppComposerSnapshot | None
    content_source: Literal["default", "latest_group", "latest_recipient"]
    target_state: WhatsAppRecipientMessageStateModel | None


async def load_preview_selection(
    session: AsyncSession,
    group_id: uuid.UUID,
    body: WhatsAppPreviewRequest,
    current_user: User,
) -> PreviewSelection:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )
    require_active_broadcast(group)
    all_recipients = await _group_recipients(session, group.id)
    if not all_recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This WhatsApp list has no recipients",
        )
    if body.recipient_id and body.resend_recipient_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose either a preview recipient or a resend recipient, not both",
        )
    source_recipients = _select_group_recipients(all_recipients, body.recipient_ids)
    message_type = _as_message_type(body.message_type)
    audience_resolution = await resolve_reminder_audience(
        session,
        message_request=body,
        broadcast_group=group,
        recipients=source_recipients,
        audience=body.audience,
        audience_client_group_id=body.audience_client_group_id,
        current_user=current_user,
        roster_recipients=all_recipients,
    )
    recipients = list(audience_resolution.recipients)
    if not recipients:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No recipients match the selected audience filters.",
        )
    if (
        body.resend_recipient_id
        and body.recipient_ids is not None
        and (len(recipients) != 1 or recipients[0].id != body.resend_recipient_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A resend preview can only target its selected recipient",
        )
    recipient = select_preview_recipient(recipients, body.resend_recipient_id or body.recipient_id)
    return PreviewSelection(
        group, source_recipients, audience_resolution, recipients, recipient, message_type
    )


async def load_preview_snapshot(
    session: AsyncSession,
    body: WhatsAppPreviewRequest,
    group: WhatsAppBroadcastGroupModel,
    recipient: WhatsAppBroadcastRecipientModel,
    message_type: WhatsAppMessageType,
) -> PreviewSavedSnapshot:
    target_state: WhatsAppRecipientMessageStateModel | None = None
    snapshot: _WhatsAppComposerSnapshot | None = None
    content_source: Literal["default", "latest_group", "latest_recipient"] = "default"
    if body.resend_recipient_id:
        if message_type == "group_invite":
            invite_blocks = await group_invite_blocking_statuses(session, [recipient])
            if recipient.id in invite_blocks:
                raise HTTPException(
                    status_code=409, detail=group_invite_block_message(invite_blocks[recipient.id])
                )
        state_result = await session.execute(
            select(WhatsAppRecipientMessageStateModel).where(
                WhatsAppRecipientMessageStateModel.recipient_id == body.resend_recipient_id,
                WhatsAppRecipientMessageStateModel.message_type == message_type,
            )
        )
        target_state = state_result.scalar_one_or_none()
        if not target_state or (
            target_state.status not in WHATSAPP_ACCEPTED_STATUSES
            and target_state.status != "failed"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only a sent or failed WhatsApp message can be opened here",
            )
        snapshot = await _latest_composer_snapshot(
            session,
            group_id=group.id,
            recipient_id=body.resend_recipient_id,
            message_type=message_type,
            accepted_only=target_state.status in WHATSAPP_ACCEPTED_STATUSES,
            include_failed=target_state.status == "failed",
            include_explicit_resends=True,
        )
        if snapshot:
            content_source = "latest_recipient"
    if snapshot is None and body.resend_recipient_id is None:
        snapshot = await _latest_composer_snapshot(
            session,
            group_id=group.id,
            message_type=message_type,
            accepted_only=True,
        )
        if snapshot:
            content_source = "latest_group"
    if body.resend_recipient_id is not None and snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No saved message is available to resend or retry for this recipient",
        )
    return PreviewSavedSnapshot(snapshot, content_source, target_state)
