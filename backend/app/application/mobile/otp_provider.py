"""Provider-neutral OTP delivery contract.

The application owns challenge creation, hashing, expiry, and attempts. A
provider receives only the destination, one-time code, and bounded TTL.
"""

from __future__ import annotations

from typing import Protocol

from app.core.config.settings import get_settings


class OTPDeliveryError(RuntimeError):
    """Raised when no OTP provider can safely deliver a code."""


class OTPProvider(Protocol):
    async def send_code(
        self,
        *,
        normalized_phone: str,
        code: str,
        expires_in_seconds: int,
    ) -> str | None:
        """Deliver one code and return a provider message identifier if available."""


class DisabledOTPProvider:
    async def send_code(
        self,
        *,
        normalized_phone: str,
        code: str,
        expires_in_seconds: int,
    ) -> str | None:
        del normalized_phone, code, expires_in_seconds
        raise OTPDeliveryError("OTP delivery is not configured")


class DevelopmentOTPProvider:
    """Test-only provider; delivery is intentionally a no-op."""

    async def send_code(
        self,
        *,
        normalized_phone: str,
        code: str,
        expires_in_seconds: int,
    ) -> str | None:
        del normalized_phone, code, expires_in_seconds
        if get_settings().is_production:
            raise OTPDeliveryError("The development OTP provider is disabled in production")
        return "development"


def get_otp_provider() -> OTPProvider:
    provider = get_settings().mobile.otp_provider
    if provider == "development":
        return DevelopmentOTPProvider()
    return DisabledOTPProvider()
