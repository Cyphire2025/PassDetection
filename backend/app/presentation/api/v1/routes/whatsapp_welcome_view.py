"""Phone-scoped welcome projections for existing list checklists and previews."""

from __future__ import annotations

import uuid
from datetime import UTC

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.welcome_policy import requires_prior_welcome
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppPhoneWelcomeAttemptModel,
    WhatsAppPhoneWelcomeModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.phone_welcome import (
    WELCOME_DELIVERED_STATUSES,
    WELCOME_REQUIRED,
    welcome_states_for_phones,
)


async def overlay_broadcast_traveller_welcomes(
    session: AsyncSession,
    recipients: list[WhatsAppBroadcastRecipientModel],
    states_by_recipient: dict[uuid.UUID, list[WhatsAppRecipientMessageStateModel]],
) -> None:
    """Include actual traveller sends belonging to this broadcast and destination."""
    if not recipients:
        return
    attempt = WhatsAppPhoneWelcomeAttemptModel
    keys = {
        (recipient.agency_id, recipient.broadcast_group_id, recipient.normalized_phone_number)
        for recipient in recipients
    }
    ranked = select(
        attempt.id, attempt.agency_id, attempt.broadcast_group_id,
        attempt.normalized_phone_number, attempt.status, attempt.status_updated_at,
        attempt.created_at,
        func.row_number().over(
            partition_by=(attempt.agency_id, attempt.broadcast_group_id, attempt.normalized_phone_number),
            order_by=(attempt.created_at.desc(), attempt.id.desc()),
        ).label("attempt_order"),
    ).where(tuple_(
        attempt.agency_id, attempt.broadcast_group_id, attempt.normalized_phone_number,
    ).in_(keys)).subquery()
    rows = (await session.execute(select(ranked).where(ranked.c.attempt_order == 1))).all()
    by_destination = {
        (row.agency_id, row.broadcast_group_id, row.normalized_phone_number): row
        for row in rows
    }
    for recipient in recipients:
        row = by_destination.get((
            recipient.agency_id, recipient.broadcast_group_id, recipient.normalized_phone_number,
        ))
        if row is None:
            continue
        states = states_by_recipient.setdefault(recipient.id, [])
        previous = next((state for state in states if state.message_type == "welcome"), None)
        accepted_rank = {"submitted": 1, "sent": 2, "delivered": 3, "read": 4}
        if previous is not None and (
            (accepted_rank.get(previous.status, 0), previous.status_updated_at.replace(tzinfo=UTC))
            >= (accepted_rank.get(row.status, 0), row.status_updated_at.replace(tzinfo=UTC))
        ):
            continue
        states[:] = [state for state in states if state.message_type != "welcome"]
        states.append(WhatsAppRecipientMessageStateModel(
            id=row.id, recipient_id=recipient.id, agency_id=recipient.agency_id,
            broadcast_group_id=recipient.broadcast_group_id, message_type="welcome",
            status=row.status, status_updated_at=row.status_updated_at,
        ))


async def phone_welcome_statuses_by_recipient(
    session: AsyncSession,
    recipients: list[WhatsAppBroadcastRecipientModel],
) -> dict[uuid.UUID, str | None]:
    """Read global welcome prerequisites separately from broadcast delivery."""
    if not recipients:
        return {}
    rows = (
        (
            await session.execute(
                select(WhatsAppPhoneWelcomeModel).where(
                    WhatsAppPhoneWelcomeModel.agency_id.in_(
                        {recipient.agency_id for recipient in recipients}
                    ),
                    WhatsAppPhoneWelcomeModel.normalized_phone_number.in_(
                        {recipient.normalized_phone_number for recipient in recipients}
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    by_phone = {(row.agency_id, row.normalized_phone_number): row for row in rows}
    return {
        recipient.id: (
            row.status
            if (row := by_phone.get((recipient.agency_id, recipient.normalized_phone_number)))
            is not None
            else None
        )
        for recipient in recipients
    }


async def welcome_preview_values(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    recipients: list[WhatsAppBroadcastRecipientModel],
    message_type: str,
    selected_recipient_id: uuid.UUID | None = None,
) -> dict[str, object]:
    if message_type != "welcome" and not requires_prior_welcome(message_type):
        return {"welcome_required_count": 0, "welcome_required_reason": None}
    if selected_recipient_id is not None:
        recipients = [recipient for recipient in recipients if recipient.id == selected_recipient_id]
    states = await welcome_states_for_phones(
        session,
        agency_id=agency_id,
        phones=[recipient.normalized_phone_number for recipient in recipients],
    )
    current = [states.get(recipient.normalized_phone_number) for recipient in recipients]
    if message_type == "welcome":
        accepted = sum(status in {"submitted", "sent", "delivered", "read"} for status in current)
        pending = sum(status in {"queued", "processing"} for status in current)
        unknown = current.count("delivery_unknown")
        return {
            "eligible_recipient_count": len(current) - accepted - pending - unknown,
            "already_sent_count": accepted,
            "in_progress_count": pending,
            "uncertain_recipient_count": unknown,
        }
    required = sum(status not in WELCOME_DELIVERED_STATUSES for status in current)
    return {
        "welcome_required_count": required,
        "welcome_required_reason": WELCOME_REQUIRED if required else None,
        **({"eligible_recipient_count": 0} if required else {}),
    }


def welcome_resend_skip_reason(message_type: str, phone_status: str | None) -> str | None:
    if message_type != "welcome":
        return (
            "skipped_welcome_required"
            if requires_prior_welcome(message_type) and phone_status not in WELCOME_DELIVERED_STATUSES
            else None
        )
    if phone_status in {"submitted", "sent", "delivered", "read"}:
        return "skipped_already_sent"
    if phone_status in {"queued", "processing"}:
        return "skipped_in_progress"
    if phone_status == "delivery_unknown":
        return "skipped_delivery_unknown"
    return None
