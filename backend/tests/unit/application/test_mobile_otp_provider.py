from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.application.mobile import otp_provider


@pytest.mark.asyncio
async def test_development_provider_never_returns_the_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        otp_provider,
        "get_settings",
        lambda: SimpleNamespace(is_production=False),
    )
    result = await otp_provider.DevelopmentOTPProvider().send_code(
        normalized_phone="+919999999999",
        code="123456",
        expires_in_seconds=300,
    )
    assert result == "development"
    assert "123456" not in result


@pytest.mark.asyncio
async def test_development_provider_fails_closed_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        otp_provider,
        "get_settings",
        lambda: SimpleNamespace(is_production=True),
    )
    with pytest.raises(otp_provider.OTPDeliveryError):
        await otp_provider.DevelopmentOTPProvider().send_code(
            normalized_phone="+919999999999",
            code="123456",
            expires_in_seconds=300,
        )

@pytest.mark.asyncio
async def test_disabled_provider_fails_without_leaking_destination() -> None:
    with pytest.raises(otp_provider.OTPDeliveryError, match="not configured"):
        await otp_provider.DisabledOTPProvider().send_code(
            normalized_phone="+919999999999",
            code="123456",
            expires_in_seconds=300,
        )
