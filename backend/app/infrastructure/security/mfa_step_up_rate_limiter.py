"""Bounded, temporary abuse controls for authenticated MFA step-up."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis

from app.core.config.settings import get_settings

_INCREMENT_AND_LOCK_SCRIPT = """
local failure_key = KEYS[1]
local lock_key = KEYS[2]
local window_seconds = tonumber(ARGV[1])
local maximum = tonumber(ARGV[2])
local lock_seconds = tonumber(ARGV[3])

local count = redis.call('INCR', failure_key)
local current_ttl = redis.call('TTL', failure_key)
if current_ttl < 0 then
    redis.call('EXPIRE', failure_key, window_seconds)
end
if count >= maximum then
    redis.call('SET', lock_key, '1', 'EX', lock_seconds)
    return {count, 1}
end
return {count, 0}
"""


class MFAStepUpLocked(RuntimeError):
    """The temporary step-up backoff is active."""


class MFAStepUpLimiterUnavailable(RuntimeError):
    """The production-wide limiter cannot make an authoritative decision."""


class MFAStepUpRateLimiter:
    """Count only authenticated failures and expire every denial automatically."""

    _local_failures: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    _local_locks: dict[str, float] = {}

    def __init__(self) -> None:
        self._settings = get_settings()
        try:
            redis_settings = self._settings.redis
            self._redis: Redis | None = Redis.from_url(
                redis_settings.security_url,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception:
            self._redis = None

    async def ensure_available(
        self,
        *,
        user_id: uuid.UUID,
        ip_address: str | None,
    ) -> None:
        keys = self._scope_keys(user_id, ip_address)
        if self._redis is not None:
            try:
                for key in keys:
                    if await self._redis.exists(f"{key}:lock"):
                        raise MFAStepUpLocked()
                return
            except MFAStepUpLocked:
                raise
            except Exception as exc:
                failed_redis = self._redis
                self._redis = None
                if failed_redis is not None:
                    await failed_redis.aclose()
                if not self._settings.is_development:
                    raise MFAStepUpLimiterUnavailable() from exc
        if not self._settings.is_development:
            raise MFAStepUpLimiterUnavailable()
        if any(self._local_locks.get(key, 0.0) > time.time() for key in keys):
            raise MFAStepUpLocked()

    async def record_failure(
        self,
        *,
        user_id: uuid.UUID,
        ip_address: str | None,
    ) -> None:
        keys = self._scope_keys(user_id, ip_address)
        maximum = self._settings.mfa_step_up_max_attempts
        if self._redis is not None:
            try:
                for key in keys:
                    result = await cast(
                        Awaitable[object],
                        self._redis.eval(
                            _INCREMENT_AND_LOCK_SCRIPT,
                            2,
                            f"{key}:failures",
                            f"{key}:lock",
                            str(self._settings.mfa_step_up_window_seconds),
                            str(maximum),
                            str(self._settings.mfa_step_up_lock_seconds),
                        ),
                    )
                    if not isinstance(result, (list, tuple)) or len(result) != 2:
                        raise RuntimeError("Unexpected MFA limiter result")
                    if int(result[1]) == 1:
                        raise MFAStepUpLocked()
                return
            except MFAStepUpLocked:
                raise
            except Exception as exc:
                failed_redis = self._redis
                self._redis = None
                if failed_redis is not None:
                    await failed_redis.aclose()
                if not self._settings.is_development:
                    raise MFAStepUpLimiterUnavailable() from exc
        if not self._settings.is_development:
            raise MFAStepUpLimiterUnavailable()
        now = time.time()
        for key in keys:
            count, expires_at = self._local_failures.get(key, (0, 0.0))
            if now >= expires_at:
                count, expires_at = 0, now + self._settings.mfa_step_up_window_seconds
            count += 1
            self._local_failures[key] = (count, expires_at)
            if count >= maximum:
                self._local_locks[key] = now + self._settings.mfa_step_up_lock_seconds
                raise MFAStepUpLocked()

    async def clear(
        self,
        *,
        user_id: uuid.UUID,
        ip_address: str | None,
    ) -> None:
        keys = self._scope_keys(user_id, ip_address)
        if self._redis is not None:
            try:
                await self._redis.delete(
                    *(item for key in keys for item in (f"{key}:failures", f"{key}:lock"))
                )
                return
            except Exception:
                failed_redis = self._redis
                self._redis = None
                if failed_redis is not None:
                    await failed_redis.aclose()
        if self._settings.is_development:
            for key in keys:
                self._local_failures.pop(key, None)
                self._local_locks.pop(key, None)
        await self.close()

    async def close(self) -> None:
        redis = self._redis
        self._redis = None
        if redis is not None:
            await redis.aclose()

    def _key(self, scope: str, user_id: uuid.UUID, value: str) -> str:
        digest = hmac.new(
            self._settings.app_secret_key.encode("utf-8"),
            f"mfa-step-up\0{scope}\0{user_id}\0{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"identity:mfa-step-up:v2:{scope}:{digest}"

    def _scope_keys(self, user_id: uuid.UUID, ip_address: str | None) -> tuple[str, str]:
        return (
            self._key("account", user_id, "all-contexts"),
            self._key("context", user_id, ip_address or "unknown"),
        )


__all__ = [
    "MFAStepUpLimiterUnavailable",
    "MFAStepUpLocked",
    "MFAStepUpRateLimiter",
]
