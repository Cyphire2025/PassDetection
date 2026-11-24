"""Independent returning-history OTP quotas; no mobile/family counter resets."""

from app.infrastructure.security.mobile_otp_rate_limiter import MobileOTPRateLimiter


class TravellerReuseRateLimiter(MobileOTPRateLimiter):
    def __init__(self) -> None:
        super().__init__()
        # Returning-history disclosure must not inherit a relaxed mobile flag.
        # Copy settings so the independent existing mobile flow is unaffected.
        if not self._settings.is_development:
            self._mobile = self._mobile.model_copy(update={"otp_require_redis": True})

    def _key(self, scope: str, value: str) -> str:
        return "traveller-reuse:" + super()._key(scope, value)
