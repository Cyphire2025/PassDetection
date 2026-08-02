from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.infrastructure.security.mobile_otp_rate_limiter import (
    MobileOTPRateLimiter,
    OTPRateLimitExceeded,
    OTPRateLimitUnavailable,
)


def _limiter(*, require_redis: bool, development: bool = True) -> MobileOTPRateLimiter:
    limiter = MobileOTPRateLimiter.__new__(MobileOTPRateLimiter)
    limiter._settings = SimpleNamespace(is_development=development)
    limiter._mobile = SimpleNamespace(
        otp_phone_limit_per_hour=2,
        otp_ip_limit_per_hour=3,
        otp_require_redis=require_redis,
    )
    limiter._redis = None
    limiter._local_counts = {}
    return limiter


@pytest.mark.asyncio
async def test_local_fallback_bounds_phone_requests_in_development() -> None:
    limiter = _limiter(require_redis=False)
    await limiter.consume(normalized_phone="+919999999999", ip_address="192.0.2.1")
    await limiter.consume(normalized_phone="+919999999999", ip_address="192.0.2.1")
    with pytest.raises(OTPRateLimitExceeded):
        await limiter.consume(normalized_phone="+919999999999", ip_address="192.0.2.1")


@pytest.mark.asyncio
async def test_missing_redis_fails_closed_outside_development() -> None:
    limiter = _limiter(require_redis=True, development=False)
    with pytest.raises(OTPRateLimitUnavailable):
        await limiter.consume(normalized_phone="+919999999999", ip_address="192.0.2.1")
