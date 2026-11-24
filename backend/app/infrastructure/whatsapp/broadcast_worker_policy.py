"""Frozen template and current recipient authority checks for one worker item."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import (
    WhatsAppMessageType,
    validate_template_parameters,
)
from app.application.use_cases.whatsapp.welcome_policy import requires_prior_welcome
from app.core.config.settings import Settings
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_resolution_id_for_recipient,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_block_message,
    group_invite_blocking_statuses,
    message_phone_blocking_statuses,
    passport_link_block_message,
)
from app.infrastructure.whatsapp.phone_welcome import WELCOME_REQUIRED, require_welcome_delivered


@dataclass(frozen=True, slots=True)
class BroadcastPolicyCallbacks:
    settings: Callable[[], Settings]
    authorize_mcp: Callable[..., Awaitable[str | None]]
    assert_welcome: Callable[..., Awaitable[bool]]


def _resolve_log_template_snapshot(
    *,
    log: WhatsAppMessageLogModel,
    message_type: WhatsAppMessageType,
    fallback_header_parameters: list[str],
    fallback_parameters: list[str],
) -> tuple[list[str], list[str]]:
    saved_header = getattr(log, "header_parameter_values", None)
    saved_body = getattr(log, "template_parameter_values", None)
    if saved_header is None and saved_body is None:
        if getattr(log, "is_explicit_resend", False):
            raise ValueError("Explicit resend is missing its frozen template parameters")
        if message_type == "group_invite":
            validate_template_parameters(
                message_type=message_type,
                header_parameters=fallback_header_parameters,
                body_parameters=fallback_parameters,
            )
        return fallback_header_parameters, fallback_parameters
    if not isinstance(saved_header, list) or not isinstance(saved_body, list):
        raise ValueError("Saved WhatsApp template parameters are incomplete")
    if any(not isinstance(value, str) for value in [*saved_header, *saved_body]):
        raise ValueError("Saved WhatsApp template parameters are invalid")
    header_parameters = list(saved_header)
    parameters = list(saved_body)
    validate_template_parameters(
        message_type=message_type,
        header_parameters=header_parameters,
        body_parameters=parameters,
    )
    return header_parameters, parameters


async def _load_sendable_recipient(
    session: AsyncSession,
    *,
    log: WhatsAppMessageLogModel,
    expected_batch_id: uuid.UUID,
    include_previous_recipients: bool = False,
    callbacks: BroadcastPolicyCallbacks,
) -> tuple[WhatsAppBroadcastRecipientModel | None, str | None]:
    mcp_error = await callbacks.authorize_mcp(session, log=log, settings=callbacks.settings())
    if mcp_error:
        return None, mcp_error
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(WhatsAppBroadcastGroupModel.id == log.broadcast_group_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    group = group_result.scalar_one_or_none()
    if not group:
        return None, "WhatsApp broadcast group no longer exists"
    if getattr(group, "archived_at", None) is not None:
        return None, "WhatsApp broadcast is archived. Restore it before sending messages."

    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(WhatsAppBroadcastRecipientModel.id == log.recipient_id)
        .execution_options(populate_existing=True)
    )
    recipient = recipient_result.scalar_one_or_none()
    if not recipient:
        return None, "WhatsApp recipient no longer exists"
    if recipient.removed_at is not None:
        return None, "WhatsApp recipient was removed"
    if await active_replacement_resolution_id_for_recipient(
        session,
        recipient=recipient,
    ):
        return None, "WhatsApp recipient was replaced in a linked passport group"

    frozen_phone = getattr(log, "normalized_phone_number", None)
    if not frozen_phone or frozen_phone != recipient.normalized_phone_number:
        return None, "WhatsApp destination changed or lacks a safe snapshot. Review and send again."
    if log.message_type == "group_invite":
        invite_blocks = await group_invite_blocking_statuses(session, [recipient], current_log=log)
        if recipient.id in invite_blocks:
            return None, group_invite_block_message(invite_blocks[recipient.id])
    if log.message_type == "passport_link":
        phone_blocks = await message_phone_blocking_statuses(
            session,
            [recipient],
            message_type="passport_link",
            current_log=log,
            include_accepted=not (
                log.is_explicit_resend
                or include_previous_recipients
                or (getattr(log, "document_update_context", None) or {}).get("passport_link_repeat")
                is True
            ),
        )
        if recipient.id in phone_blocks:
            return None, passport_link_block_message(phone_blocks[recipient.id])
    if log.message_type == "welcome":
        if not await callbacks.assert_welcome(
            session,
            agency_id=log.agency_id,
            phone=frozen_phone,
            attempt_id=log.id,
            broadcast_group_id=log.broadcast_group_id,
        ):
            return None, "This number already has a welcome or another welcome is in progress."
    elif requires_prior_welcome(log.message_type) and not await require_welcome_delivered(
        session,
        agency_id=log.agency_id,
        phone=frozen_phone,
        broadcast_group_id=log.broadcast_group_id,
    ):
        return None, WELCOME_REQUIRED
    if getattr(log, "is_explicit_resend", False):
        resend_claim_result = await session.execute(
            select(WhatsAppMessageLogModel.id).where(
                WhatsAppMessageLogModel.id == log.id,
                WhatsAppMessageLogModel.batch_id == expected_batch_id,
                WhatsAppMessageLogModel.status == "processing",
                WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            )
        )
        if not resend_claim_result.scalar_one_or_none():
            return None, "Explicit resend claim was superseded before provider submission"
        return recipient, None

    state_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel).where(
            WhatsAppRecipientMessageStateModel.recipient_id == log.recipient_id,
            WhatsAppRecipientMessageStateModel.message_type == log.message_type,
        )
    )
    delivery_state = state_result.scalar_one_or_none()
    if (
        not delivery_state
        or delivery_state.batch_id != expected_batch_id
        or delivery_state.status != "processing"
    ):
        return None, "Delivery claim was superseded before provider submission"
    return recipient, None
