"""Login lockout using Redis with a local development fallback."""

from __future__ import annotations

import time
from collections import defaultdict

from redis.asyncio import Redis

from app.core.config.settings import get_settings
from app.domain.exceptions.exceptions import AuthenticationError


class LoginAttemptLimiter:
    _local_counts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    _local_locks: dict[str, float] = {}

    def __init__(self) -> None:
        self._settings = get_settings()
        self._jwt = self._settings.jwt
        self._redis: Redis | None = None
        try:
            self._redis = Redis.from_url(self._settings.redis.url, encoding="utf-8", decode_responses=True)
        except Exception:
            self._redis = None

    async def check_allowed(self, *, email: str, ip_address: str | None) -> None:
        key = self._key(email, ip_address)
        if self._redis is not None:
            try:
                if await self._redis.exists(f"{key}:locked"):
                    raise AuthenticationError("Too many failed login attempts. Try again later.")
                return
            except AuthenticationError:
                raise
            except Exception:
                self._redis = None

        if self._local_locks.get(key, 0) > time.time():
            raise AuthenticationError("Too many failed login attempts. Try again later.")

    async def record_failure(self, *, email: str, ip_address: str | None) -> None:
        key = self._key(email, ip_address)
        if self._redis is not None:
            try:
                count = await self._redis.incr(f"{key}:count")
                if count == 1:
                    await self._redis.expire(f"{key}:count", self._jwt.login_lockout_window_seconds)
                if int(count) >= self._jwt.login_lockout_max_attempts:
                    await self._redis.setex(f"{key}:locked", self._jwt.login_lockout_seconds, "1")
                return
            except Exception:
                self._redis = None

        now = time.time()
        count, expires_at = self._local_counts[key]
        if now > expires_at:
            count = 0
            expires_at = now + self._jwt.login_lockout_window_seconds
        count += 1
        self._local_counts[key] = (count, expires_at)
        if count >= self._jwt.login_lockout_max_attempts:
            self._local_locks[key] = now + self._jwt.login_lockout_seconds

    async def record_success(self, *, email: str, ip_address: str | None) -> None:
        key = self._key(email, ip_address)
        if self._redis is not None:
            try:
                await self._redis.delete(f"{key}:count", f"{key}:locked")
                return
            except Exception:
                self._redis = None
        self._local_counts.pop(key, None)
        self._local_locks.pop(key, None)

    @staticmethod
    def _key(email: str, ip_address: str | None) -> str:
        normalized_email = email.lower().strip()
        ip = ip_address or "unknown"
        return f"login-attempt:{normalized_email}:{ip}"
