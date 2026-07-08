"""
No-op WhatsApp provider.

Use this in tests and dry runs until a real BSP provider is selected and
credentials are configured. It never sends a network request.
"""

from __future__ import annotations

from app.application.dtos.whatsapp_dtos import PlannedWhatsAppMessage
from app.application.interfaces.whatsapp_provider import WhatsAppSendResult


class NoopWhatsAppProvider:
    async def send_template_message(self, message: PlannedWhatsAppMessage) -> WhatsAppSendResult:
        return WhatsAppSendResult(
            recipient_phone=message.recipient.phone_number,
            provider_message_id=None,
            status="dry_run",
        )
