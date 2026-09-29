"""Delivery-claim response accounting shared by broadcast send paths."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.presentation.api.v1.routes.whatsapp_composer_support import _message_values
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_IN_PROGRESS_STATUSES,
    WHATSAPP_SUPPRESSED_STATUSES,
    WHATSAPP_UNCERTAIN_STATUSES,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendRequest, WhatsAppSendResult


async def unclaimed_delivery_counts(
    session: AsyncSession,
    *,
    recipient_ids: list[uuid.UUID],
    message_type: str,
) -> tuple[int, int, int]:
    """Count accepted, active, and uncertain claims without changing eligibility."""
    if not recipient_ids:
        return 0, 0, 0
    result = await session.execute(
        select(WhatsAppRecipientMessageStateModel.status).where(
            WhatsAppRecipientMessageStateModel.recipient_id.in_(recipient_ids),
            WhatsAppRecipientMessageStateModel.message_type == message_type,
        )
    )
    statuses = list(result.scalars().all())
    return (
        sum(delivery_status in WHATSAPP_ACCEPTED_STATUSES for delivery_status in statuses),
        sum(delivery_status in WHATSAPP_IN_PROGRESS_STATUSES for delivery_status in statuses),
        sum(
            delivery_status
            not in (WHATSAPP_ACCEPTED_STATUSES | WHATSAPP_IN_PROGRESS_STATUSES | {"failed"})
            for delivery_status in statuses
        ),
    )


def add_frozen_broadcast_logs(
    session: AsyncSession,
    *,
    group: WhatsAppBroadcastGroupModel,
    recipients: list[WhatsAppBroadcastRecipientModel],
    support_contacts: list[WhatsAppBroadcastSupportContactModel],
    body: WhatsAppSendRequest,
    batch_id: uuid.UUID,
    now: datetime,
    template_name: str,
    log_ids: dict[uuid.UUID, uuid.UUID],
    template_language: str | None = None,
) -> list[WhatsAppSendResult]:
    """Freeze content and destination in the same transaction as both claims."""
    results: list[WhatsAppSendResult] = []
    for recipient in recipients:
        _, _, _, _, _, rendered, headers, parameters = _message_values(
            group=group,
            recipient=recipient,
            support_contacts=support_contacts,
            body=body,
        )
        session.add(
            WhatsAppMessageLogModel(
                id=log_ids.get(recipient.id, uuid.uuid4()),
                normalized_phone_number=recipient.normalized_phone_number,
                batch_id=batch_id,
                broadcast_group_id=group.id,
                recipient_id=recipient.id,
                agency_id=recipient.agency_id,
                message_type=body.message_type,
                status="queued",
                status_updated_at=now,
                provider_message_id=None,
                error_message=None,
                template_name=template_name,
                template_language=template_language,
                rendered_message=rendered,
                header_parameter_values=headers,
                template_parameter_values=parameters,
                is_explicit_resend=False,
                created_at=now,
            )
        )
        results.append(
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status="queued",
            )
        )
    return results


def broadcast_suppression_statuses(
    message_type: str, suppress_unknown_reminders: bool
) -> frozenset[str]:
    """Web reminders are deliberate repeats; MCP conservatively blocks unknown outcomes."""
    if message_type != "reminder":
        return WHATSAPP_SUPPRESSED_STATUSES
    return WHATSAPP_IN_PROGRESS_STATUSES | (
        WHATSAPP_UNCERTAIN_STATUSES if suppress_unknown_reminders else frozenset()
    )


async def release_stale_broadcast_claims(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    message_type: str,
    now: datetime,
    stale_cutoff: datetime,
) -> None:
    # Other message types may reclaim a queued task that has not contacted Meta.
    # An invite remains blocked while any queued attempt still exists. A stale
    # processing task may have submitted bytes before a worker interruption,
    # so it becomes delivery_unknown. Automatic retry remains suppressed;
    # a deliberate new reminder is a separate attempt and may replace it.
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group_id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status == "queued",
            WhatsAppMessageLogModel.message_type != "group_invite",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="Delivery claim expired before provider submission",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group_id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status == "processing",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=now,
            error_message=(
                "Delivery outcome is unknown after a worker interruption; "
                "automatic resend is suppressed"
            ),
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.broadcast_group_id == group_id,
            WhatsAppRecipientMessageStateModel.message_type == message_type,
            WhatsAppRecipientMessageStateModel.status == "processing",
            WhatsAppRecipientMessageStateModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
