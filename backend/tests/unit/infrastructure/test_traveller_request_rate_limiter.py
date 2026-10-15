"""Security quotas are independent, bounded, private, and fail closed."""

from unittest.mock import AsyncMock

import pytest

from app.core.config.traveller_reuse import TravellerReuseSettings
from app.infrastructure.security import traveller_request_rate_limiter as module
from app.infrastructure.security.mobile_otp_rate_limiter import (
    OTPRateLimitExceeded,
    OTPRateLimitUnavailable,
)


def limiter(test_settings, monkeypatch, *, environment="development"):
    settings = test_settings.model_copy(update={"app_env": environment})
    redis = AsyncMock()
    monkeypatch.setattr(module.Redis, "from_url", lambda *args, **kwargs: redis)
    return module.TravellerRequestRateLimiter(settings, TravellerReuseSettings(
        request_network_limit_per_minute=3, request_session_limit_per_minute=2,
    ))


@pytest.mark.asyncio
async def test_session_and_network_counters_are_independent(test_settings, monkeypatch):
    subject = limiter(test_settings, monkeypatch)
    monkeypatch.setattr(module, "increment_with_ttl_atomic", AsyncMock(side_effect=ConnectionError))
    await subject.consume(ip_address="first-network", session_secret="opaque-secret")
    await subject.consume(ip_address="second-network", session_secret="opaque-secret")
    with pytest.raises(OTPRateLimitExceeded):
        await subject.consume(ip_address="third-network", session_secret="opaque-secret")
    assert all("opaque-secret" not in key and "network" not in key.split(":")[-1] for key in subject._local)
    for index in range(3):
        await subject.consume(ip_address="shared-network", session_secret=f"rotated-{index}")
    with pytest.raises(OTPRateLimitExceeded):
        await subject.consume(ip_address="shared-network", session_secret="rotated-again")


@pytest.mark.asyncio
async def test_production_cannot_fall_back_when_redis_fails(test_settings, monkeypatch):
    subject = limiter(test_settings, monkeypatch, environment="production")
    monkeypatch.setattr(module, "increment_with_ttl_atomic", AsyncMock(side_effect=ConnectionError))
    with pytest.raises(OTPRateLimitUnavailable):
        await subject.consume(ip_address="network", session_secret=None)
    assert not subject._local


@pytest.mark.asyncio
async def test_local_capacity_never_evicts_active_counter(test_settings, monkeypatch):
    subject = limiter(test_settings, monkeypatch)
    subject.MAX_LOCAL_COUNTERS = 2
    monkeypatch.setattr(module, "increment_with_ttl_atomic", AsyncMock(side_effect=ConnectionError))
    await subject.consume(ip_address="network-a", session_secret=None)
    await subject.consume(ip_address="network-b", session_secret=None)
    with pytest.raises(OTPRateLimitUnavailable):
        await subject.consume(ip_address="network-c", session_secret=None)
    assert len(subject._local) == 2


@pytest.mark.asyncio
async def test_successful_redis_path_uses_atomic_ttl_counter(test_settings, monkeypatch):
    subject = limiter(test_settings, monkeypatch, environment="production")
    atomic = AsyncMock(return_value=1)
    monkeypatch.setattr(module, "increment_with_ttl_atomic", atomic)
    await subject.consume(ip_address="network", session_secret="secret")
    assert atomic.await_count == 2
    assert all(call.kwargs["ttl_seconds"] == 60 for call in atomic.await_args_list)
    assert not subject._local
    await subject.close()
    subject._redis.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_returning_otp_production_ignores_relaxed_mobile_flag_and_closes_pool(test_settings, monkeypatch):
    from app.infrastructure.security import mobile_otp_rate_limiter as mobile
    from app.infrastructure.security.traveller_reuse_rate_limiter import TravellerReuseRateLimiter

    settings = test_settings.model_copy(update={"app_env": "production"})
    monkeypatch.setenv("MOBILE_OTP_REQUIRE_REDIS", "false")
    monkeypatch.setattr(mobile, "get_settings", lambda: settings)
    redis = AsyncMock()
    monkeypatch.setattr(mobile.Redis, "from_url", lambda *args, **kwargs: redis)
    monkeypatch.setattr(mobile, "increment_with_ttl_atomic", AsyncMock(side_effect=ConnectionError))
    subject = TravellerReuseRateLimiter()
    assert subject._mobile.otp_require_redis
    with pytest.raises(OTPRateLimitUnavailable):
        await subject.consume(normalized_phone="+15555550100", ip_address="synthetic-network")
    redis.aclose.assert_awaited_once()
