"""Independent public claim/session quotas, including routes without OTP.

Redis fixed-window counters work across workers. Production fails closed if
Redis is unavailable; development fallback retains at most 10,000 counters.
O(1) per Redis counter; local pruning is amortized O(1), bounded O(10,000) space.
Only HMAC digests of network addresses and opaque tokens are stored.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import OrderedDict
from functools import lru_cache

from redis.asyncio import Redis

from app.core.config.settings import Settings, get_settings
from app.core.config.traveller_reuse import TravellerReuseSettings, get_traveller_reuse_settings
from app.infrastructure.security.mobile_otp_rate_limiter import (
    OTPRateLimitExceeded,
    OTPRateLimitUnavailable,
)
from app.infrastructure.security.redis_atomic_counter import increment_with_ttl_atomic


class TravellerRequestRateLimiter:
    MAX_LOCAL_COUNTERS = 10_000

    def __init__(self, settings: Settings, reuse_settings: TravellerReuseSettings) -> None:
        self._settings = settings
        self._reuse_settings = reuse_settings
        self._local: OrderedDict[str, tuple[int, float]] = OrderedDict()
        self._redis = Redis.from_url(settings.redis.security_url, encoding="utf-8", decode_responses=True,
            socket_timeout=1, socket_connect_timeout=1, max_connections=100)

    async def consume(self, *, ip_address: str | None, session_secret: str | None) -> None:
        await self._consume(self._key("network", ip_address or "unknown"),
                            self._reuse_settings.request_network_limit_per_minute)
        if session_secret:
            await self._consume(self._key("session", session_secret),
                                self._reuse_settings.request_session_limit_per_minute)

    async def _consume(self, key: str, limit: int) -> None:
        try:
            count = await increment_with_ttl_atomic(self._redis, key=key, ttl_seconds=60)
        except Exception as exc:
            if not self._settings.is_development:
                raise OTPRateLimitUnavailable() from exc
            count = self._consume_local(key)
        if count > limit:
            raise OTPRateLimitExceeded()

    def _consume_local(self, key: str) -> int:
        now = time.monotonic()
        # Ordered by initial expiry, never by access, so expiry pruning cannot
        # accidentally discard a still-active counter and reset its budget.
        while self._local and next(iter(self._local.values()))[1] <= now:
            self._local.popitem(last=False)
        count, expires_at = self._local.get(key, (0, now + 60))
        if key not in self._local and len(self._local) >= self.MAX_LOCAL_COUNTERS:
            raise OTPRateLimitUnavailable()
        self._local[key] = (count + 1, expires_at)
        return count + 1

    def _key(self, scope: str, value: str) -> str:
        digest = hmac.new(self._settings.app_secret_key.encode(),
            f"traveller-request\0{scope}\0{value}".encode(), hashlib.sha256).hexdigest()
        return f"traveller-request:v1:{scope}:{digest}"

    async def close(self) -> None:
        await self._redis.aclose()


@lru_cache
def get_traveller_request_limiter() -> TravellerRequestRateLimiter:
    return TravellerRequestRateLimiter(get_settings(), get_traveller_reuse_settings())


async def close_traveller_request_limiter() -> None:
    if get_traveller_request_limiter.cache_info().currsize:
        await get_traveller_request_limiter().close()
        get_traveller_request_limiter.cache_clear()
