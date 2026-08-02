"""Redis-backed OTP abuse limits with a development-only local fallback."""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict

from redis.asyncio import Redis

from app.core.config.settings import get_settings


class OTPRateLimitExceeded(RuntimeError):
    pass


class OTPRateLimitUnavailable(RuntimeError):
    pass


class MobileOTPRateLimiter:
    _local_counts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    def __init__(self) -> None:
        self._settings = get_settings()
        self._mobile = self._settings.mobile
        try:
            self._redis: Redis | None = Redis.from_url(
                self._settings.redis.url,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception:
            self._redis = None

    async def consume(self, *, normalized_phone: str, ip_address: str | None) -> None:
        phone_key = self._key("phone", normalized_phone)
        ip_key = self._key("ip", ip_address or "unknown")
        limits = (
            (phone_key, self._mobile.otp_phone_limit_per_hour),
            (ip_key, self._mobile.otp_ip_limit_per_hour),
        )
        if self._redis is not None:
            try:
                for key, limit in limits:
                    count = int(await self._redis.incr(key))
                    if count == 1:
                        await self._redis.expire(key, 3600)
                    if count > limit:
                        raise OTPRateLimitExceeded()
                return
            except OTPRateLimitExceeded:
                raise
            except Exception as exc:
                self._redis = None
                if self._mobile.otp_require_redis:
                    raise OTPRateLimitUnavailable() from exc

        if self._mobile.otp_require_redis and not self._settings.is_development:
            raise OTPRateLimitUnavailable()
        now = time.time()
        for key, limit in limits:
            count, expires_at = self._local_counts.get(key, (0, 0.0))
            if now >= expires_at:
                count, expires_at = 0, now + 3600
            count += 1
            self._local_counts[key] = (count, expires_at)
            if count > limit:
                raise OTPRateLimitExceeded()

    @staticmethod
    def _key(scope: str, value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return f"mobile-otp:v1:{scope}:{digest}"
