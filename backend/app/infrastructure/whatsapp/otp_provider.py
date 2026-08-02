"""WhatsApp Cloud API adapter for the provider-neutral mobile OTP contract."""

from __future__ import annotations

import httpx

from app.application.mobile.otp_provider import (
    DevelopmentOTPProvider,
    DisabledOTPProvider,
    OTPDeliveryError,
    OTPProvider,
)
from app.application.use_cases.whatsapp.contact_normalization import (
    normalize_whatsapp_phone,
)
from app.core.config.settings import Settings, get_settings
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_authentication_template,
)


class WhatsAppOTPProvider:
    """Deliver one OTP using an approved Meta authentication template."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client

    async def send_code(
        self,
        *,
        normalized_phone: str,
        code: str,
        expires_in_seconds: int,
    ) -> str | None:
        if normalize_whatsapp_phone(normalized_phone) != normalized_phone:
            raise OTPDeliveryError(
                "WhatsApp verification delivery failed",
                code="OTP_DESTINATION_INVALID",
            )
        if len(code) != 6 or not code.isascii() or not code.isdigit():
            raise OTPDeliveryError(
                "WhatsApp verification delivery failed",
                code="OTP_CODE_INVALID",
            )
        if not 60 <= expires_in_seconds <= 900:
            raise OTPDeliveryError(
                "WhatsApp verification delivery failed",
                code="OTP_EXPIRY_INVALID",
            )

        if self._client is not None:
            return await self._send(self._client, normalized_phone, code)

        timeout_seconds = self._settings.mobile.otp_delivery_timeout_seconds
        timeout = httpx.Timeout(timeout_seconds, connect=min(5.0, timeout_seconds))
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await self._send(client, normalized_phone, code)

    async def _send(
        self,
        client: httpx.AsyncClient,
        normalized_phone: str,
        code: str,
    ) -> str:
        try:
            return await send_whatsapp_authentication_template(
                client=client,
                settings=self._settings,
                to_number=normalized_phone,
                template_name=self._settings.whatsapp_otp_template_name,
                language_code=self._settings.whatsapp_otp_template_language,
                code=code,
            )
        except WhatsAppCloudApiError as exc:
            # Never propagate Meta response text, the destination, or OTP into
            # mobile auth logs/audits. The bounded code is enough to operate.
            raise OTPDeliveryError(
                "WhatsApp verification delivery failed",
                code=exc.code,
                transient=exc.transient,
                delivery_unknown=exc.delivery_unknown,
            ) from exc


def get_otp_provider(settings: Settings | None = None) -> OTPProvider:
    """Resolve the configured provider without a production fallback."""

    resolved = settings or get_settings()
    provider = resolved.mobile.otp_provider
    if provider == "development":
        return DevelopmentOTPProvider()
    if provider == "whatsapp":
        return WhatsAppOTPProvider(resolved)
    return DisabledOTPProvider()
