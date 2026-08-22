"""Login lockout using Redis with an explicit non-production fallback."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict

from redis.asyncio import Redis

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import AuthenticationError, DependencyUnavailableError
from app.infrastructure.security.redis_atomic_counter import increment_with_ttl_atomic

logger = get_logger(__name__)


class LoginAttemptLimiter:
    _local_counts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    _local_locks: dict[str, float] = {}

    def __init__(self) -> None:
        self._settings = get_settings()
        self._jwt = self._settings.jwt
        self._key_secret = self._settings.app_secret_key.encode("utf-8")
        self._redis: Redis | None = None
        try:
            self._redis = Redis.from_url(
                self._settings.redis.url, encoding="utf-8", decode_responses=True
            )
        except Exception as exc:
            self._handle_redis_failure("configure", exc)

    async def aclose(self) -> None:
        """Release the request-scoped Redis pool deterministically."""

        client = self._redis
        self._redis = None
        if client is not None:
            await client.aclose()

    async def check_allowed(self, *, email: str, ip_address: str | None) -> None:
        key = self._key(email, ip_address)
        if self._redis is not None:
            try:
                if await self._redis.exists(f"{key}:locked"):
                    raise AuthenticationError("Too many failed login attempts. Try again later.")
                return
            except AuthenticationError:
                raise
            except Exception as exc:
                await self._handle_redis_runtime_failure("check", exc)

        if self._local_locks.get(key, 0) > time.time():
            raise AuthenticationError("Too many failed login attempts. Try again later.")

    async def record_failure(self, *, email: str, ip_address: str | None) -> None:
        key = self._key(email, ip_address)
        if self._redis is not None:
            try:
                count = await increment_with_ttl_atomic(
                    self._redis,
                    key=f"{key}:count",
                    ttl_seconds=self._jwt.login_lockout_window_seconds,
                )
                if int(count) >= self._jwt.login_lockout_max_attempts:
                    await self._redis.setex(f"{key}:locked", self._jwt.login_lockout_seconds, "1")
                return
            except Exception as exc:
                await self._handle_redis_runtime_failure("record_failure", exc)

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
            except Exception as exc:
                await self._handle_redis_runtime_failure("record_success", exc)
        self._local_counts.pop(key, None)
        self._local_locks.pop(key, None)

    def _handle_redis_failure(self, operation: str, exc: Exception) -> None:
        self._redis = None
        logger.warning(
            "login_lockout_redis_unavailable",
            operation=operation,
            error_type=type(exc).__name__,
        )
        if self._settings.login_lockout_require_redis:
            raise DependencyUnavailableError(
                "Authentication is temporarily unavailable. Please try again shortly."
            ) from exc

    async def _handle_redis_runtime_failure(self, operation: str, exc: Exception) -> None:
        client = self._redis
        self._redis = None
        if client is not None:
            try:
                await client.aclose()
            except Exception as close_exc:
                logger.warning(
                    "login_lockout_redis_close_failed",
                    operation=operation,
                    error_type=type(close_exc).__name__,
                )
        self._handle_redis_failure(operation, exc)

    def _key(self, email: str, ip_address: str | None) -> str:
        normalized_email = email.lower().strip()
        ip = ip_address or "unknown"
        digest = hmac.new(
            self._key_secret,
            f"login-lockout\0{normalized_email}\0{ip}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"login-attempt:v2:{digest}"
