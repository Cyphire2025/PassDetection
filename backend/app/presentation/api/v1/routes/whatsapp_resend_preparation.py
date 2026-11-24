"""Validate saved content and stage its one immutable resend attempt."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.core.config.settings import get_settings
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.presentation.api.v1.routes.whatsapp_history_resend import (
    frozen_resend_values,
    saved_resend_source,
    saved_template_name,
)
from app.presentation.api.v1.routes.whatsapp_phone_welcome import claim_resend_welcome_or_reject
from app.presentation.api.v1.routes.whatsapp_resend_claims import ResendClaim
from app.presentation.api.v1.routes.whatsapp_shared import (
    _merge_composer_snapshot,
    _message_values,
    _resolve_message_links,
    _resolve_send_header_image,
    _resolve_send_message_content,
    _resolve_send_passport_intro,
    _select_support_contacts,
    _snapshot_template_language,
    _support_contacts_for_group,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppResendRequest,
    WhatsAppSendRequest,
)


@dataclass(frozen=True)
class PreparedResend:
    source_log: WhatsAppMessageLogModel
    batch_id: uuid.UUID
    header_parameters: list[str]
    parameters: list[str]


async def prepare_resend_attempt(
    session: AsyncSession,
    group: WhatsAppBroadcastGroupModel,
    recipient: WhatsAppBroadcastRecipientModel,
    body: WhatsAppResendRequest,
    message_type: WhatsAppMessageType,
    history_batch: uuid.UUID | None,
    claim: ResendClaim,
) -> PreparedResend:
    delivery_state = claim.delivery_state
    is_retry = claim.is_retry
    now = claim.now
    source_log, source_snapshot = await saved_resend_source(
        session,
        group_id=group.id,
        recipient_id=recipient.id,
        message_type=message_type,
        is_retry=is_retry,
        source_message_log_id=body.source_message_log_id,
    )
    settings = get_settings()
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp Cloud API credentials are incomplete",
        )
    effective_template_name = await saved_template_name(session, message_type, body, source_log)
    merged_body = _merge_composer_snapshot(body, source_snapshot)
    header_image_id = _resolve_send_header_image(
        message_type,
        merged_body.header_image_id,
        resend=True,
    )
    support_contacts = _select_support_contacts(
        await _support_contacts_for_group(session, group.id),
        merged_body.support_contact_ids,
        message_type=message_type,
    )
    if message_type == "passport_link" and not support_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add customer support contacts before resending this message",
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
    passport_link, group_invite_link = _resolve_message_links(merged_body)
    resolved_body = WhatsAppSendRequest(
        message_type=message_type,
        passport_intro=passport_intro,
        passport_link=passport_link,
        message_content=message_content,
        group_invite_link=group_invite_link,
        header_image_id=header_image_id,
        recipient_ids=merged_body.recipient_ids,
        support_contact_ids=merged_body.support_contact_ids,
    )
    rendered_message: str | None
    (
        _,
        _,
        _,
        _,
        _,
        rendered_message,
        header_parameters,
        parameters,
    ) = _message_values(
        group=group,
        recipient=recipient,
        support_contacts=support_contacts,
        body=resolved_body,
    )
    template_name = effective_template_name.strip()
    if not template_name:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"WhatsApp {message_type} template name is not configured",
        )
    template_name, header_parameters, parameters, rendered_message = frozen_resend_values(
        body, source_log, template_name, header_parameters, parameters, rendered_message
    )
    batch_id = history_batch or uuid.uuid4()
    resend_log = WhatsAppMessageLogModel(
        id=uuid.uuid4(),
        normalized_phone_number=recipient.normalized_phone_number,
        batch_id=batch_id,
        broadcast_group_id=group.id,
        recipient_id=recipient.id,
        agency_id=recipient.agency_id,
        message_type=message_type,
        status="queued",
        status_updated_at=now,
        provider_message_id=None,
        error_message=None,
        template_name=template_name,
        template_language=_snapshot_template_language(settings, message_type, source_log),
        rendered_message=rendered_message,
        header_parameter_values=header_parameters,
        template_parameter_values=parameters,
        is_explicit_resend=not is_retry,
        created_at=now,
    )
    await claim_resend_welcome_or_reject(session, resend_log)
    session.add(resend_log)
    if is_retry:
        delivery_state.status = "queued"
        delivery_state.batch_id = batch_id
        delivery_state.submitted_at = None
        delivery_state.provider_status_at = None
        delivery_state.status_updated_at = now
        delivery_state.updated_at = now
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A resend of this message is already active for this recipient.",
        ) from exc
    return PreparedResend(source_log, batch_id, header_parameters, parameters)
