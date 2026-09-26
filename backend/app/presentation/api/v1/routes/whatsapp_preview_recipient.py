"""Recipient selection within an already authorized preview audience."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status

from app.infrastructure.database.models import WhatsAppBroadcastRecipientModel


def select_preview_recipient(
    recipients: list[WhatsAppBroadcastRecipientModel], selected_recipient_id: uuid.UUID | None,
) -> WhatsAppBroadcastRecipientModel:
    recipient = recipients[0]
    if selected_recipient_id:
        selected = next(
            (item for item in recipients if item.id == selected_recipient_id),
            None,
        )
        if not selected:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Preview recipient not found in this WhatsApp list",
            )
        recipient = selected

    return recipient
