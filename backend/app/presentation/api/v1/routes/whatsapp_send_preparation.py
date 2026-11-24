"""Load and validate the concrete broadcast audience and editable message facts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.application.use_cases.whatsapp.recipient_capacity import (
    MAX_WHATSAPP_RECIPIENTS,
    WhatsAppRecipientCapacityExceeded,
    require_whatsapp_recipient_capacity,
)
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
)
from app.presentation.api.v1.routes.whatsapp_archive_policy import require_active_broadcast
from app.presentation.api.v1.routes.whatsapp_phone_welcome import (
    enforce_broadcast_welcome_prerequisite,
)
from app.presentation.api.v1.routes.whatsapp_reminder_audience import (
    ReminderAudienceResolution,
    resolve_reminder_audience,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _agency_filter,
    _as_message_type,
    _group_recipients,
    _latest_composer_snapshot,
    _merge_composer_snapshot,
    _resolve_send_header_image,
    _resolve_send_message_content,
    _resolve_send_passport_intro,
    _select_group_recipients,
    _select_support_contacts,
    _support_contacts_for_group,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendRequest


@dataclass(frozen=True, slots=True)
class PreparedBroadcastSend:
    group: WhatsAppBroadcastGroupModel
    message_type: WhatsAppMessageType
    source_recipients: list[WhatsAppBroadcastRecipientModel]
    audience_resolution: ReminderAudienceResolution
    recipients: list[WhatsAppBroadcastRecipientModel]
    support_contacts: list[WhatsAppBroadcastSupportContactModel]
    merged_body: WhatsAppSendRequest
    header_image_id: str | None
    message_content: str
    passport_intro: str | None


async def prepare_broadcast_send(
    group_id: uuid.UUID,
    body: WhatsAppSendRequest,
    *,
    current_user: User,
    session: AsyncSession,
) -> PreparedBroadcastSend:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp broadcast group not found"
        )
    require_active_broadcast(group)
    if group.recipient_opt_in_confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient WhatsApp opt-in has not been confirmed for this list",
        )

    all_recipients = await _group_recipients(session, group.id)
    if not all_recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This WhatsApp list has no recipients",
        )
    try:
        require_whatsapp_recipient_capacity(
            active_count=len(all_recipients),
            activating_count=0,
        )
    except WhatsAppRecipientCapacityExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This WhatsApp list exceeds the maximum of "
                f"{MAX_WHATSAPP_RECIPIENTS} recipients. Remove extra recipients before sending."
            ),
        ) from exc
    message_type = _as_message_type(body.message_type)
    source_recipients = _select_group_recipients(all_recipients, body.recipient_ids)
    audience_resolution = await resolve_reminder_audience(
        session,
        message_request=body,
        broadcast_group=group,
        recipients=source_recipients,
        audience=body.audience,
        audience_client_group_id=body.audience_client_group_id,
        current_user=current_user,
    )
    recipients = list(audience_resolution.recipients)
    await enforce_broadcast_welcome_prerequisite(
        session,
        agency_id=group.agency_id,
        message_type=message_type,
        recipients=recipients,
    )
    support_contacts = await _support_contacts_for_group(session, group.id)
    snapshot = await _latest_composer_snapshot(
        session,
        group_id=group.id,
        message_type=message_type,
        accepted_only=True,
    )
    merged_body = _merge_composer_snapshot(body, snapshot)
    support_contacts = _select_support_contacts(
        support_contacts,
        merged_body.support_contact_ids,
        message_type=message_type,
    )
    if message_type == "passport_link" and not support_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add customer support contacts before sending this message",
        )
    header_image_id = _resolve_send_header_image(
        message_type,
        merged_body.header_image_id,
    )
    message_content = _resolve_send_message_content(
        message_type,
        merged_body.message_content,
        group_name=group.name,
    )
    passport_intro = (
        _resolve_send_passport_intro(
            merged_body.passport_intro,
            group_name=group.name,
        )
        if message_type == "passport_link"
        else None
    )
    return PreparedBroadcastSend(
        group=group,
        message_type=message_type,
        source_recipients=source_recipients,
        audience_resolution=audience_resolution,
        recipients=recipients,
        support_contacts=support_contacts,
        merged_body=merged_body,
        header_image_id=header_image_id,
        message_content=message_content,
        passport_intro=passport_intro,
    )
