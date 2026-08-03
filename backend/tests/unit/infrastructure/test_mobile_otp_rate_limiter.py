from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.infrastructure.security.mobile_otp_rate_limiter import (
    MobileOTPRateLimiter,
    OTPRateLimitExceeded,
    OTPRateLimitUnavailable,
)


class _AtomicCounterRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.eval_calls: list[tuple[str, int]] = []
        self.fail = fail

    async def eval(
        self,
        script: str,
        numkeys: int,
        key: str,
        ttl_seconds: int,
    ) -> int:
        if self.fail:
            raise ConnectionError("redis unavailable")
        assert numkeys == 1
        assert "redis.call('INCR', key)" in script
        assert "redis.call('TTL', key)" in script
        assert "redis.call('EXPIRE', key, ttl_seconds)" in script
        self.eval_calls.append((key, ttl_seconds))
        self.counts[key] = self.counts.get(key, 0) + 1
        if key not in self.ttls:
            self.ttls[key] = ttl_seconds
        return self.counts[key]


def _limiter(*, require_redis: bool, development: bool = True) -> MobileOTPRateLimiter:
    limiter = MobileOTPRateLimiter.__new__(MobileOTPRateLimiter)
    limiter._settings = SimpleNamespace(is_development=development)
    limiter._key_secret = b"test-app-secret-key"
    limiter._mobile = SimpleNamespace(
        otp_phone_limit_per_hour=2,
        otp_ip_limit_per_hour=3,
        otp_require_redis=require_redis,
    )
    limiter._redis = None
    limiter._local_counts = {}
    return limiter


@pytest.mark.asyncio
async def test_redis_first_increment_sets_ttl_in_same_eval() -> None:
    limiter = _limiter(require_redis=True, development=False)
    redis = _AtomicCounterRedis()
    limiter._redis = redis  # type: ignore[assignment]

    await limiter.consume(normalized_phone="+919999999999", ip_address="192.0.2.1")

    phone_key = limiter._key("phone", "+919999999999")
    ip_key = limiter._key("ip", "192.0.2.1")
    assert redis.eval_calls == [(phone_key, 3600), (ip_key, 3600)]
    assert redis.ttls == {phone_key: 3600, ip_key: 3600}


@pytest.mark.asyncio
async def test_redis_increment_preserves_existing_ttl() -> None:
    limiter = _limiter(require_redis=True, development=False)
    redis = _AtomicCounterRedis()
    phone_key = limiter._key("phone", "+919999999999")
    ip_key = limiter._key("ip", "192.0.2.1")
    redis.counts.update({phone_key: 1, ip_key: 1})
    redis.ttls.update({phone_key: 1200, ip_key: 900})
    limiter._redis = redis  # type: ignore[assignment]

    await limiter.consume(normalized_phone="+919999999999", ip_address="192.0.2.1")

    assert redis.counts == {phone_key: 2, ip_key: 2}
    assert redis.ttls == {phone_key: 1200, ip_key: 900}


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


@pytest.mark.asyncio
async def test_redis_eval_failure_retains_fail_closed_policy() -> None:
    limiter = _limiter(require_redis=True, development=False)
    limiter._redis = _AtomicCounterRedis(fail=True)  # type: ignore[assignment]

    with pytest.raises(OTPRateLimitUnavailable):
        await limiter.consume(normalized_phone="+919999999999", ip_address="192.0.2.1")


@pytest.mark.asyncio
async def test_redis_eval_failure_retains_explicit_local_fallback_policy() -> None:
    limiter = _limiter(require_redis=False)
    limiter._redis = _AtomicCounterRedis(fail=True)  # type: ignore[assignment]

    await limiter.consume(normalized_phone="+919999999999", ip_address="192.0.2.1")

    assert limiter._redis is None
    assert sorted(count for count, _expires_at in limiter._local_counts.values()) == [1, 1]


def test_otp_keys_are_stable_and_contain_no_phone_or_ip() -> None:
    limiter = _limiter(require_redis=False)

    phone_key = limiter._key("phone", "+919999999999")
    ip_key = limiter._key("ip", "192.0.2.1")

    assert phone_key == limiter._key("phone", "+919999999999")
    assert ip_key == limiter._key("ip", "192.0.2.1")
    assert phone_key.startswith("mobile-otp:v2:phone:")
    assert ip_key.startswith("mobile-otp:v2:ip:")
    assert len(phone_key.rsplit(":", 1)[-1]) == 64
    assert "+919999999999" not in phone_key
    assert "192.0.2.1" not in ip_key


def test_otp_keys_isolate_scope_identity_and_secret() -> None:
    limiter = _limiter(require_redis=False)
    other_secret_limiter = _limiter(require_redis=False)
    other_secret_limiter._key_secret = b"different-test-app-secret-key"

    base = limiter._key("phone", "+919999999999")

    assert limiter._key("phone", "+919999999998") != base
    assert limiter._key("ip", "+919999999999") != base
    assert other_secret_limiter._key("phone", "+919999999999") != base
