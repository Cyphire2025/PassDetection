"""Enumeration-safe, Redis-backed password-recovery abuse controls."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from collections import defaultdict

from redis.asyncio import Redis

from app.core.config.settings import get_settings
from app.infrastructure.security.redis_atomic_counter import increment_with_ttl_atomic


class IdentityRecoveryRateLimited(RuntimeError):
    pass


class IdentityRecoveryRateLimiterUnavailable(RuntimeError):
    pass


class IdentityRecoveryRateLimiter:
    """Limit network risk first, then a verified account and its tenant.

    Account limits suppress replacement issuance but never invalidate the most
    recently issued token. An attacker who knows an email therefore cannot use
    request spam to continuously revoke a legitimate user's recovery link.
    """

    _local_counts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))

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

    async def consume_network(
        self,
        *,
        ip_address: str | None,
        risk_context: str | None,
    ) -> None:
        """Consume independent IP and risk-context budgets.

        Keeping these as separate counters is intentional.  A combined
        ``IP + user-agent`` key lets a caller evade the IP budget by rotating
        user agents, while a user-agent-only limit would let the same client
        evade it by changing addresses.  Missing proxy context is handled as
        one bounded fallback key instead of disabling the control.
        """

        try:
            consumed_scope = False
            if ip_address:
                await self._consume(
                    self._key("ip", ip_address),
                    self._settings.password_recovery_ip_limit_per_hour,
                )
                consumed_scope = True
            if risk_context:
                await self._consume(
                    self._key("risk", risk_context),
                    self._settings.password_recovery_ip_limit_per_hour,
                )
                consumed_scope = True
            if not consumed_scope:
                await self._consume(
                    self._key("network", "unknown"),
                    self._settings.password_recovery_ip_limit_per_hour,
                )
        finally:
            await self.close()

    async def consume_account(
        self,
        *,
        user_id: uuid.UUID,
        agency_id: uuid.UUID | None,
    ) -> None:
        try:
            await self._consume(
                self._key("account", str(user_id)),
                self._settings.password_recovery_account_limit_per_hour,
            )
            await self._consume(
                self._key("tenant", str(agency_id or "platform")),
                self._settings.password_recovery_tenant_limit_per_hour,
            )
        finally:
            await self.close()

    async def _consume(self, key: str, limit: int) -> None:
        if self._redis is not None:
            try:
                count = await increment_with_ttl_atomic(
                    self._redis,
                    key=key,
                    ttl_seconds=3_600,
                )
                if count > limit:
                    raise IdentityRecoveryRateLimited()
                return
            except IdentityRecoveryRateLimited:
                raise
            except Exception as exc:
                failed_redis = self._redis
                self._redis = None
                if failed_redis is not None:
                    await failed_redis.aclose()
                if self._settings.password_recovery_rate_limit_require_redis:
                    raise IdentityRecoveryRateLimiterUnavailable() from exc
        if (
            self._settings.password_recovery_rate_limit_require_redis
            and not self._settings.is_development
        ):
            raise IdentityRecoveryRateLimiterUnavailable()
        now = time.time()
        count, expires_at = self._local_counts.get(key, (0, 0.0))
        if now >= expires_at:
            count, expires_at = 0, now + 3_600
        count += 1
        self._local_counts[key] = (count, expires_at)
        if count > limit:
            raise IdentityRecoveryRateLimited()

    async def close(self) -> None:
        redis = self._redis
        self._redis = None
        if redis is not None:
            await redis.aclose()

    def _key(self, scope: str, value: str) -> str:
        digest = hmac.new(
            self._settings.app_secret_key.encode("utf-8"),
            f"identity-recovery-rate-limit\0{scope}\0{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"identity:recovery-limit:v1:{scope}:{digest}"


__all__ = [
    "IdentityRecoveryRateLimited",
    "IdentityRecoveryRateLimiter",
    "IdentityRecoveryRateLimiterUnavailable",
]
