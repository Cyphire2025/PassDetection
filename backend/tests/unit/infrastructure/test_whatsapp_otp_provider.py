from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application.mobile.otp_provider import (
    DevelopmentOTPProvider,
    DisabledOTPProvider,
    OTPDeliveryError,
)
from app.infrastructure.whatsapp import otp_provider
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError


def _settings(provider: str = "whatsapp") -> SimpleNamespace:
    return SimpleNamespace(
        mobile=SimpleNamespace(
            otp_provider=provider,
            otp_delivery_timeout_seconds=10.0,
        ),
        whatsapp_otp_template_name="verify_code_1",
        whatsapp_otp_template_language="en_US",
    )


@pytest.mark.asyncio
async def test_whatsapp_provider_uses_normalized_destination_and_returns_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = AsyncMock(return_value="wamid.otp-123")
    monkeypatch.setattr(
        otp_provider,
        "send_whatsapp_authentication_template",
        transport,
    )
    client = SimpleNamespace()
    settings = _settings()
    provider = otp_provider.WhatsAppOTPProvider(settings, client=client)

    provider_id = await provider.send_code(
        normalized_phone="+919876543210",
        code="483920",
        expires_in_seconds=300,
    )

    assert provider_id == "wamid.otp-123"
    transport.assert_awaited_once_with(
        client=client,
        settings=settings,
        to_number="+919876543210",
        template_name="verify_code_1",
        language_code="en_US",
        code="483920",
    )


@pytest.mark.asyncio
async def test_whatsapp_provider_rejects_noncanonical_phone_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = AsyncMock()
    monkeypatch.setattr(
        otp_provider,
        "send_whatsapp_authentication_template",
        transport,
    )
    provider = otp_provider.WhatsAppOTPProvider(_settings(), client=SimpleNamespace())

    with pytest.raises(OTPDeliveryError) as raised:
        await provider.send_code(
            normalized_phone="9876543210",
            code="483920",
            expires_in_seconds=300,
        )

    assert raised.value.code == "OTP_DESTINATION_INVALID"
    assert "9876543210" not in str(raised.value)
    transport.assert_not_awaited()


@pytest.mark.asyncio
async def test_whatsapp_provider_maps_meta_failure_to_pii_safe_otp_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = AsyncMock(
        side_effect=WhatsAppCloudApiError(
            "provider payload should remain internal",
            code="WHATSAPP_DELIVERY_UNKNOWN",
            delivery_unknown=True,
        )
    )
    monkeypatch.setattr(
        otp_provider,
        "send_whatsapp_authentication_template",
        transport,
    )
    provider = otp_provider.WhatsAppOTPProvider(_settings(), client=SimpleNamespace())

    with pytest.raises(OTPDeliveryError) as raised:
        await provider.send_code(
            normalized_phone="+919876543210",
            code="483920",
            expires_in_seconds=300,
        )

    assert raised.value.code == "WHATSAPP_DELIVERY_UNKNOWN"
    assert raised.value.delivery_unknown is True
    assert "provider payload" not in str(raised.value)
    assert "919876543210" not in str(raised.value)
    assert "483920" not in str(raised.value)


def test_factory_is_fail_closed_and_keeps_development_provider() -> None:
    assert isinstance(
        otp_provider.get_otp_provider(_settings("disabled")),
        DisabledOTPProvider,
    )
    assert isinstance(
        otp_provider.get_otp_provider(_settings("development")),
        DevelopmentOTPProvider,
    )
    assert isinstance(
        otp_provider.get_otp_provider(_settings("whatsapp")),
        otp_provider.WhatsAppOTPProvider,
    )
