"""Login lockout using Redis with an explicit non-production fallback."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import AuthenticationError, DependencyUnavailableError
from app.infrastructure.security.redis_atomic_counter import increment_with_ttl_atomic

logger = get_logger(__name__)

# Fixed windows do not extend when an attacker retries a denied account. This
# short admission budget is deliberately separate from the existing per-pair
# failed-password lockout. Successful logins cannot erase the shared budgets.
_ADMISSION_WINDOW_SECONDS = 60
_ACCOUNT_ATTEMPTS = 20
_IP_ATTEMPTS = 120
_GLOBAL_ATTEMPTS = 1200
_ADMIT = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
for i = 2, #KEYS do
  if redis.call('EXISTS', KEYS[i]) == 1 and redis.call('TTL', KEYS[i]) < 0 then
    redis.call('EXPIRE', KEYS[i], ARGV[1])
  end
  if tonumber(redis.call('GET', KEYS[i]) or '0') >= tonumber(ARGV[i]) then return 0 end
end
for i = 2, #KEYS do
  local count = redis.call('INCR', KEYS[i])
  if count == 1 or redis.call('TTL', KEYS[i]) < 0 then
    redis.call('EXPIRE', KEYS[i], ARGV[1])
  end
end
return 1
"""


class LoginAttemptLimiter:
    _local_counts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    _local_locks: dict[str, float] = {}
    _local_admission: dict[str, tuple[int, float]] = {}

    def __init__(self) -> None:
        self._settings = get_settings()
        self._jwt = self._settings.jwt
        self._key_secret = self._settings.app_secret_key.encode("utf-8")
        self._redis: Redis | None = None
        try:
            self._redis = Redis.from_url(
                self._settings.redis.security_url, encoding="utf-8", decode_responses=True
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
        budgets = self._admission_keys(email, ip_address)
        if self._redis is not None:
            try:
                allowed = await cast(Awaitable[object], self._redis.eval(
                    _ADMIT, 4, f"{key}:locked", *budgets,
                    str(_ADMISSION_WINDOW_SECONDS), str(_ACCOUNT_ATTEMPTS), str(_IP_ATTEMPTS), str(_GLOBAL_ATTEMPTS),
                ))
                if isinstance(allowed, bool) or not isinstance(allowed, int) or allowed not in (0, 1):
                    raise TypeError("Redis admission returned an invalid result")
                if not allowed:
                    raise AuthenticationError("Too many failed login attempts. Try again later.")
                return
            except AuthenticationError:
                raise
            except Exception as exc:
                await self._handle_redis_runtime_failure("check", exc)

        if self._local_locks.get(key, 0) > time.time():
            raise AuthenticationError("Too many failed login attempts. Try again later.")
        now = time.time()
        # No await between checking and reserving: the development fallback
        # has the same admission semantics within one event loop only.
        self._local_admission = type(self)._local_admission
        for expired in [k for k, (_, expiry) in self._local_admission.items() if expiry <= now]:
            self._local_admission.pop(expired, None)
        for budget, maximum in zip(budgets, (_ACCOUNT_ATTEMPTS, _IP_ATTEMPTS, _GLOBAL_ATTEMPTS), strict=True):
            if self._local_admission.get(budget, (0, 0))[0] >= maximum:
                raise AuthenticationError("Too many failed login attempts. Try again later.")
        for budget in budgets:
            count, expiry = self._local_admission.get(budget, (0, now + _ADMISSION_WINDOW_SECONDS))
            self._local_admission[budget] = (count + 1, expiry)

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

    def _admission_keys(self, email: str, ip_address: str | None) -> tuple[str, str, str]:
        def key(scope: str, value: str) -> str:
            digest = hmac.new(self._key_secret, f"login-budget\0{scope}\0{value}".encode(), hashlib.sha256).hexdigest()
            return f"login-admission:v1:{scope}:{digest}"
        return (
            key("account", email.strip().lower()),
            key("ip", ip_address or "unknown"),
            key("global", "all"),
        )
