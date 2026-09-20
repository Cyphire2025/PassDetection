"""Family-sized public upload quotas isolated from mobile login quotas."""

from __future__ import annotations

import hashlib
import hmac

from app.infrastructure.security.mobile_otp_rate_limiter import MobileOTPRateLimiter


class PublicUploadOTPRateLimiter(MobileOTPRateLimiter):
    def __init__(self) -> None:
        super().__init__()
        self._mobile = self._mobile.model_copy(update={
            "otp_phone_limit_per_hour": self._settings.public_upload_otp_phone_limit_per_hour,
            "otp_ip_limit_per_hour": self._settings.public_upload_otp_ip_limit_per_hour,
        })

    def _key(self, scope: str, value: str) -> str:
        digest = hmac.new(
            self._key_secret,
            f"public-upload-otp-rate-limit\0{scope}\0{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"public-upload-otp:v1:{scope}:{digest}"
