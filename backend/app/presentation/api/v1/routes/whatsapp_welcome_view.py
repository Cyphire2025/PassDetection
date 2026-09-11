"""Phone-scoped welcome projections for existing list checklists and previews."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppPhoneWelcomeModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.phone_welcome import (
    WELCOME_DELIVERED_STATUSES,
    WELCOME_REQUIRED,
    welcome_states_for_phones,
)


async def overlay_phone_welcome_states(
    session: AsyncSession,
    recipients: list[WhatsAppBroadcastRecipientModel],
    states_by_recipient: dict[uuid.UUID, list[WhatsAppRecipientMessageStateModel]],
) -> None:
    """Project immutable phone history without changing recipient-specific rows."""
    if not recipients:
        return
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
    for recipient in recipients:
        states = [
            state
            for state in states_by_recipient.get(recipient.id, [])
            if state.message_type != "welcome"
        ]
        row = by_phone.get((recipient.agency_id, recipient.normalized_phone_number))
        if row is not None:
            states.append(
                WhatsAppRecipientMessageStateModel(
                    id=row.id,
                    recipient_id=recipient.id,
                    broadcast_group_id=recipient.broadcast_group_id,
                    agency_id=recipient.agency_id,
                    message_type="welcome",
                    status=row.status,
                    submitted_at=row.delivered_at,
                    status_updated_at=row.status_updated_at,
                )
            )
        states_by_recipient[recipient.id] = states


async def welcome_preview_values(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    recipients: list[WhatsAppBroadcastRecipientModel],
    message_type: str,
    selected_recipient_id: uuid.UUID | None = None,
) -> dict[str, object]:
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
            "skipped_welcome_required" if phone_status not in WELCOME_DELIVERED_STATUSES else None
        )
    if phone_status in {"submitted", "sent", "delivered", "read"}:
        return "skipped_already_sent"
    if phone_status in {"queued", "processing"}:
        return "skipped_in_progress"
    if phone_status == "delivery_unknown":
        return "skipped_delivery_unknown"
    return None
