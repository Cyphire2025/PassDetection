"""Family uploads retain bounded OTP quotas independent of mobile login."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.infrastructure.security.mobile_otp_rate_limiter import OTPRateLimitExceeded
from app.infrastructure.security.public_upload_otp_rate_limiter import PublicUploadOTPRateLimiter


async def test_default_quota_supports_twenty_members_and_still_stops_at_bound(test_settings):
    assert test_settings.public_upload_otp_phone_limit_per_hour == 30
    assert test_settings.public_upload_otp_ip_limit_per_hour == 60
    with patch("app.infrastructure.security.mobile_otp_rate_limiter.get_settings", return_value=test_settings):
        limiter = PublicUploadOTPRateLimiter()
    limiter._redis = None
    limiter._mobile = limiter._mobile.model_copy(update={"otp_require_redis": False})
    limiter._local_counts = {}
    phone = "+919876543210"
    for _ in range(30):
        await limiter.consume(normalized_phone=phone, ip_address="192.0.2.10")
    with pytest.raises(OTPRateLimitExceeded):
        await limiter.consume(normalized_phone=phone, ip_address="192.0.2.10")
    assert limiter._key("phone", phone).startswith("public-upload-otp:v1:phone:")
    assert phone not in limiter._key("phone", phone)


async def test_public_upload_quota_does_not_consume_mobile_login_allowance(test_settings):
    from app.infrastructure.security.mobile_otp_rate_limiter import MobileOTPRateLimiter

    with patch("app.infrastructure.security.mobile_otp_rate_limiter.get_settings", return_value=test_settings):
        public = PublicUploadOTPRateLimiter()
        mobile = MobileOTPRateLimiter()
    for limiter in (public, mobile):
        limiter._redis = None
        limiter._mobile = limiter._mobile.model_copy(update={"otp_require_redis": False})
    public._local_counts = mobile._local_counts = {}
    phone = "+919876543210"
    for _ in range(20):
        await public.consume(normalized_phone=phone, ip_address="192.0.2.10")
    await mobile.consume(normalized_phone=phone, ip_address="192.0.2.10")
    assert mobile._local_counts[mobile._key("phone", phone)][0] == 1
    assert public._local_counts[public._key("phone", phone)][0] == 20
