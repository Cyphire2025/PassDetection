"""
WhatsApp provider contract for future BSP integration.

Concrete providers should adapt Meta Cloud API, Twilio, Interakt, AiSensy,
MSG91, or any other BSP behind this interface. The active application does not
instantiate this interface yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.application.dtos.whatsapp_dtos import PlannedWhatsAppMessage


@dataclass(frozen=True, slots=True)
class WhatsAppSendResult:
    recipient_phone: str
    provider_message_id: str | None
    status: str
    error_message: str | None = None


class WhatsAppProvider(Protocol):
    async def send_template_message(self, message: PlannedWhatsAppMessage) -> WhatsAppSendResult:
        """Send one approved WhatsApp template message."""
