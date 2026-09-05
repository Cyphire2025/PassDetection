"""Inert WhatsApp roster fixtures for the guarded, isolated dashboard QA seed.

This helper creates no message log, delivery ledger, task, or provider request.
It leaves recipient consent unconfirmed so the UI cannot submit a broadcast.
The caller owns the database transaction and must commit the complete QA seed.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import (
    normalize_whatsapp_phone,
)
from app.core.config.settings import get_settings
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
)

_QA_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "passdetection-real-stack-qa")
_RECIPIENTS = (
    ("QA Avery", "+1 (202) 555-0101", "North team"),
    ("QA Blake", "+1 (202) 555-0102", "North team"),
    ("QA Casey", "+1 (202) 555-0103", "South team"),
    ("QA Drew", "+1 (202) 555-0104", "South team"),
)


async def seed_whatsapp_visual_records(
    session: AsyncSession,
    *,
    namespace: uuid.UUID,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> uuid.UUID:
    """Idempotently add four fictional recipients and their QA group link."""
    settings = get_settings()
    if (
        settings.app_env != "development"
        or not settings.database.db.startswith("passdetection_ci_")
        or namespace != _QA_NAMESPACE
        or agency_id != uuid.uuid5(namespace, "agency")
        or group_id != uuid.uuid5(namespace, "group")
    ):
        raise RuntimeError(
            "WhatsApp visual fixtures require the isolated development QA namespace"
        )

    broadcast_id = uuid.uuid5(namespace, "visual-whatsapp-broadcast")
    broadcast = await session.get(WhatsAppBroadcastGroupModel, broadcast_id)
    if broadcast is None:
        broadcast = WhatsAppBroadcastGroupModel(
            id=broadcast_id,
            agency_id=agency_id,
            name="QA Travel Updates",
            organizing_company_name="Synthetic visual review",
            created_by_user_id=owner_id,
            recipient_opt_in_confirmed_at=None,
        )
        session.add(broadcast)
        await session.flush()
    elif broadcast.agency_id != agency_id:
        raise RuntimeError("Existing WhatsApp QA fixture has unexpected ownership")
    # Re-running visual QA must not enable outbound messaging.
    broadcast.recipient_opt_in_confirmed_at = None

    for index, (name, phone, team) in enumerate(_RECIPIENTS):
        recipient_id = uuid.uuid5(namespace, f"visual-whatsapp-recipient-{index}")
        recipient = await session.get(WhatsAppBroadcastRecipientModel, recipient_id)
        if recipient is None:
            normalized = normalize_whatsapp_phone(phone)
            if normalized is None:
                raise RuntimeError("Invalid fictional WhatsApp fixture number")
            session.add(
                WhatsAppBroadcastRecipientModel(
                    id=recipient_id,
                    agency_id=agency_id,
                    broadcast_group_id=broadcast_id,
                    name=name,
                    phone_number=phone,
                    normalized_phone_number=normalized,
                    imported_fields={
                        "Team": team,
                        "Source": "Synthetic visual fixture",
                    },
                    display_order=index + 1,
                )
            )
        elif (
            recipient.agency_id != agency_id
            or recipient.broadcast_group_id != broadcast_id
        ):
            raise RuntimeError(
                "Existing WhatsApp QA recipient has unexpected ownership"
            )

    support_id = uuid.uuid5(namespace, "visual-whatsapp-support")
    if await session.get(WhatsAppBroadcastSupportContactModel, support_id) is None:
        session.add(
            WhatsAppBroadcastSupportContactModel(
                id=support_id,
                agency_id=agency_id,
                broadcast_group_id=broadcast_id,
                name="QA Travel Desk",
                phone_number="+1 (202) 555-0199",
                normalized_phone_number="+12025550199",
                sort_order=0,
            )
        )
    link_id = uuid.uuid5(namespace, "visual-whatsapp-client-group-link")
    if await session.get(ClientGroupWhatsAppBroadcastLinkModel, link_id) is None:
        session.add(
            ClientGroupWhatsAppBroadcastLinkModel(
                id=link_id,
                agency_id=agency_id,
                client_group_id=group_id,
                broadcast_group_id=broadcast_id,
                created_by_user_id=owner_id,
            )
        )
    await session.flush()
    return broadcast_id
