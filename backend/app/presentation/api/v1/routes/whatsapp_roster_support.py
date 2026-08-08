"""Tenant-scoped roster query helpers for WhatsApp routes."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_phone_numbers_for_broadcast,
)
from app.presentation.api.v1.routes.whatsapp_contact_support import (
    _recipient_response,
    _support_contact_response,
)
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_IN_PROGRESS_STATUSES,
    WHATSAPP_UNCERTAIN_STATUSES,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBroadcastGroupDetailResponse,
)


async def _support_contacts_for_group(
    session: AsyncSession,
    group_id: uuid.UUID,
) -> list[WhatsAppBroadcastSupportContactModel]:
    result = await session.execute(
        select(WhatsAppBroadcastSupportContactModel)
        .where(WhatsAppBroadcastSupportContactModel.broadcast_group_id == group_id)
        .order_by(
            WhatsAppBroadcastSupportContactModel.sort_order.asc(),
            WhatsAppBroadcastSupportContactModel.created_at.asc(),
        )
    )
    return list(result.scalars().all())


async def _recipient_delivery_state_maps(
    session: AsyncSession,
    recipients: list[WhatsAppBroadcastRecipientModel],
) -> tuple[
    dict[uuid.UUID, list[WhatsAppRecipientMessageStateModel]],
    dict[uuid.UUID, dict[str, str]],
]:
    states_by_recipient: dict[uuid.UUID, list[WhatsAppRecipientMessageStateModel]] = {}
    resend_statuses_by_recipient: dict[uuid.UUID, dict[str, str]] = {}
    if not recipients:
        return states_by_recipient, resend_statuses_by_recipient

    recipient_ids = [recipient.id for recipient in recipients]
    states_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel)
        .where(WhatsAppRecipientMessageStateModel.recipient_id.in_(recipient_ids))
        .order_by(WhatsAppRecipientMessageStateModel.message_type.asc())
    )
    for state_model in states_result.scalars().all():
        states_by_recipient.setdefault(state_model.recipient_id, []).append(state_model)

    resend_result = await session.execute(
        select(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id.in_(recipient_ids),
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
        )
        .order_by(WhatsAppMessageLogModel.created_at.desc())
    )
    for resend_log in resend_result.scalars().all():
        current_state = next(
            (
                state
                for state in states_by_recipient.get(resend_log.recipient_id, [])
                if state.message_type == resend_log.message_type
            ),
            None,
        )
        if (
            current_state
            and current_state.status == "failed"
            and resend_log.created_at <= current_state.status_updated_at
        ):
            continue
        recipient_statuses = resend_statuses_by_recipient.setdefault(
            resend_log.recipient_id,
            {},
        )
        recipient_statuses.setdefault(resend_log.message_type, resend_log.status)
    return states_by_recipient, resend_statuses_by_recipient


async def _group_detail(
    session: AsyncSession, group: WhatsAppBroadcastGroupModel
) -> WhatsAppBroadcastGroupDetailResponse:
    recipients = await _group_recipients(session, group.id)
    states_by_recipient, resend_statuses_by_recipient = await _recipient_delivery_state_maps(
        session, recipients
    )
    support_contacts = await _support_contacts_for_group(session, group.id)
    rejected_count_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group.id,
        )
    )
    rejected_contact_count = int(rejected_count_result.scalar_one())
    return WhatsAppBroadcastGroupDetailResponse(
        id=group.id,
        name=group.name,
        organizing_company_name=group.organizing_company_name,
        recipient_count=len(recipients),
        total_contact_count=len(recipients) + rejected_contact_count,
        recipient_opt_in_confirmed=group.recipient_opt_in_confirmed_at is not None,
        created_at=group.created_at,
        updated_at=group.updated_at,
        recipients=[
            _recipient_response(
                recipient,
                states_by_recipient.get(recipient.id, []),
                resend_statuses_by_recipient.get(recipient.id, {}),
            )
            for recipient in recipients
        ],
        support_contacts=[_support_contact_response(contact) for contact in support_contacts],
        rejected_contact_count=rejected_contact_count,
    )


async def _group_recipients(
    session: AsyncSession,
    group_id: uuid.UUID,
) -> list[WhatsAppBroadcastRecipientModel]:
    result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .order_by(
            WhatsAppBroadcastRecipientModel.name.asc().nullslast(),
            WhatsAppBroadcastRecipientModel.created_at.asc(),
        )
    )
    recipients = list(result.scalars().all())
    if not recipients:
        return []
    suppressed_phones = await active_replacement_phone_numbers_for_broadcast(
        session,
        broadcast_group_id=group_id,
        agency_id=recipients[0].agency_id,
    )
    return [
        recipient
        for recipient in recipients
        if recipient.normalized_phone_number not in suppressed_phones
    ]


def _select_group_recipients(
    recipients: list[WhatsAppBroadcastRecipientModel],
    requested_ids: list[uuid.UUID] | None,
) -> list[WhatsAppBroadcastRecipientModel]:
    """Apply an optional custom-recipient selection without widening scope."""
    if requested_ids is None:
        return recipients
    requested_id_set = set(requested_ids)
    if not requested_id_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one WhatsApp recipient",
        )
    selected = [recipient for recipient in recipients if recipient.id in requested_id_set]
    if len(selected) != len(requested_id_set):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more selected WhatsApp recipients were not found in this list",
        )
    return selected


def _select_support_contacts(
    support_contacts: list[WhatsAppBroadcastSupportContactModel],
    requested_ids: list[uuid.UUID] | None,
    *,
    message_type: WhatsAppMessageType,
) -> list[WhatsAppBroadcastSupportContactModel]:
    """Apply optional support-contact selection for Passport Link messages."""
    if message_type != "passport_link" or requested_ids is None:
        return support_contacts
    requested_id_set = set(requested_ids)
    if not requested_id_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one customer support contact",
        )
    selected = [contact for contact in support_contacts if contact.id in requested_id_set]
    if len(selected) != len(requested_id_set):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "One or more selected customer support contacts were not found "
                "in this WhatsApp list"
            ),
        )
    return selected


async def _recipient_delivery_counts(
    session: AsyncSession,
    *,
    recipients: list[WhatsAppBroadcastRecipientModel],
    message_type: str,
) -> tuple[int, int, int, int]:
    if not recipients:
        return 0, 0, 0, 0
    states_result = await session.execute(
        select(
            WhatsAppRecipientMessageStateModel.recipient_id,
            WhatsAppRecipientMessageStateModel.status,
        ).where(
            WhatsAppRecipientMessageStateModel.recipient_id.in_(
                [recipient.id for recipient in recipients]
            ),
            WhatsAppRecipientMessageStateModel.message_type == message_type,
        )
    )
    statuses = {recipient_id: state_status for recipient_id, state_status in states_result.all()}
    already_sent = sum(
        1 for state_status in statuses.values() if state_status in WHATSAPP_ACCEPTED_STATUSES
    )
    in_progress = sum(
        1 for state_status in statuses.values() if state_status in WHATSAPP_IN_PROGRESS_STATUSES
    )
    uncertain = sum(
        1 for state_status in statuses.values() if state_status in WHATSAPP_UNCERTAIN_STATUSES
    )
    return (
        len(recipients) - already_sent - in_progress - uncertain,
        already_sent,
        in_progress,
        uncertain,
    )
