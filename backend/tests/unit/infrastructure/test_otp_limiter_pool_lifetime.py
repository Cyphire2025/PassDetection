"""Request-scoped quota clients release pools without changing their decision."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.security.mobile_otp_rate_limiter import (
    MobileOTPRateLimiter,
    OTPRateLimitExceeded,
    OTPRateLimitUnavailable,
)
from app.infrastructure.security.public_upload_otp_rate_limiter import PublicUploadOTPRateLimiter
from app.infrastructure.security.traveller_reuse_rate_limiter import TravellerReuseRateLimiter


@pytest.mark.parametrize(
    "limiter_type", [MobileOTPRateLimiter, PublicUploadOTPRateLimiter, TravellerReuseRateLimiter]
)
@pytest.mark.parametrize(
    "outcome",
    ["accepted", "denied", "unavailable", "cancelled", "close_failed", "denied_close_failed"],
)
async def test_each_request_releases_its_pool_and_preserves_quota_outcome(
    monkeypatch,
    test_settings,
    limiter_type,
    outcome,
):
    redis = SimpleNamespace(eval=AsyncMock(return_value=1), aclose=AsyncMock())
    monkeypatch.setattr(
        "app.infrastructure.security.mobile_otp_rate_limiter.get_settings", lambda: test_settings
    )
    monkeypatch.setattr(
        "app.infrastructure.security.mobile_otp_rate_limiter.Redis.from_url",
        lambda *args, **kwargs: redis,
    )
    limiter = limiter_type()
    limiter._mobile = limiter._mobile.model_copy(update={"otp_require_redis": True})
    expected = None
    if outcome in {"denied", "denied_close_failed"}:
        redis.eval.return_value = 100_000
        expected = OTPRateLimitExceeded
    elif outcome == "unavailable":
        redis.eval.side_effect = ConnectionError("synthetic unavailable Redis")
        expected = OTPRateLimitUnavailable
    elif outcome == "cancelled":
        redis.eval.side_effect = asyncio.CancelledError
        expected = asyncio.CancelledError
    if outcome in {"close_failed", "denied_close_failed"}:
        redis.aclose.side_effect = RuntimeError("synthetic cleanup failure")
    if expected is None:
        await limiter.consume(normalized_phone="+15555550100", ip_address="192.0.2.5")
    else:
        with pytest.raises(expected):
            await limiter.consume(normalized_phone="+15555550100", ip_address="192.0.2.5")
    redis.aclose.assert_awaited_once()
