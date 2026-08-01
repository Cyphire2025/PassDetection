"""Shared WhatsApp recipient-capacity policy."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

MAX_WHATSAPP_RECIPIENTS = 1_500


@dataclass(frozen=True, slots=True)
class WhatsAppRecipientCapacityExceeded(ValueError):
    """Raised before a mutation would exceed one broadcast's recipient cap."""

    active_count: int
    activating_count: int
    broadcast_group_id: uuid.UUID | None = None

    @property
    def projected_count(self) -> int:
        return self.active_count + self.activating_count


def require_whatsapp_recipient_capacity(
    *,
    active_count: int,
    activating_count: int,
    broadcast_group_id: uuid.UUID | None = None,
) -> int:
    """Return the projected count or reject it using the canonical policy."""

    if active_count < 0 or activating_count < 0:
        raise ValueError("WhatsApp recipient counts cannot be negative")
    projected_count = active_count + activating_count
    if projected_count > MAX_WHATSAPP_RECIPIENTS:
        raise WhatsAppRecipientCapacityExceeded(
            active_count=active_count,
            activating_count=activating_count,
            broadcast_group_id=broadcast_group_id,
        )
    return projected_count
