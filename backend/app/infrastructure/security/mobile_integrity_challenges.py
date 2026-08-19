"""Cross-worker, one-time mobile-integrity challenge storage."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Awaitable, Protocol, cast

from redis.asyncio import Redis

from app.application.mobile.app_integrity import (
    MobileIntegrityChallenge,
    MobileIntegrityUnavailable,
)
from app.core.config.settings import Settings, get_settings

_CONSUME_LUA = """
local value = redis.call('GET', KEYS[1])
if value then redis.call('DEL', KEYS[1]) end
return value
"""
_MAX_LOCAL_CHALLENGES = 10_000


class MobileIntegrityChallengeStore(Protocol):
    async def put(self, challenge: MobileIntegrityChallenge) -> None: ...

    async def consume(self, challenge_id: uuid.UUID) -> MobileIntegrityChallenge | None: ...


@dataclass(slots=True)
class InMemoryMobileIntegrityChallengeStore:
    """Bounded single-process store for tests and explicit local development."""

    clock: Callable[[], float] = time.time
    _records: dict[uuid.UUID, MobileIntegrityChallenge] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def put(self, challenge: MobileIntegrityChallenge) -> None:
        async with self._lock:
            self._discard_expired()
            if len(self._records) >= _MAX_LOCAL_CHALLENGES:
                raise MobileIntegrityUnavailable("Local integrity challenge capacity is exhausted")
            if challenge.challenge_id in self._records:
                raise MobileIntegrityUnavailable("Integrity challenge collision")
            self._records[challenge.challenge_id] = challenge

    async def consume(self, challenge_id: uuid.UUID) -> MobileIntegrityChallenge | None:
        async with self._lock:
            challenge = self._records.pop(challenge_id, None)
            if challenge is None:
                return None
            if challenge.expires_at_epoch <= int(self.clock()):
                return None
            return challenge

    def _discard_expired(self) -> None:
        now = int(self.clock())
        expired = [
            challenge_id
            for challenge_id, challenge in self._records.items()
            if challenge.expires_at_epoch <= now
        ]
        for challenge_id in expired:
            self._records.pop(challenge_id, None)


class RedisMobileIntegrityChallengeStore:
    """Redis-backed one-time store; values contain only bounded opaque hashes."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        redis: Redis | None = None,
        local_fallback: InMemoryMobileIntegrityChallengeStore | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._require_redis = self._settings.mobile.app_integrity_require_redis
        self._redis = redis or Redis.from_url(
            self._settings.redis.url,
            encoding="utf-8",
            decode_responses=True,
        )
        self._local = local_fallback or InMemoryMobileIntegrityChallengeStore()

    async def put(self, challenge: MobileIntegrityChallenge) -> None:
        ttl = challenge.expires_at_epoch - int(time.time())
        if ttl < 1:
            raise MobileIntegrityUnavailable("Integrity challenge expired before persistence")
        try:
            stored = await self._redis.set(
                self._key(challenge.challenge_id),
                challenge.to_json(),
                ex=ttl,
                nx=True,
            )
            if not stored:
                raise MobileIntegrityUnavailable("Integrity challenge collision")
            return
        except MobileIntegrityUnavailable:
            raise
        except Exception as exc:
            if self._require_redis or not self._settings.is_development:
                raise MobileIntegrityUnavailable(
                    "Integrity challenge persistence is unavailable"
                ) from exc
        await self._local.put(challenge)

    async def consume(self, challenge_id: uuid.UUID) -> MobileIntegrityChallenge | None:
        try:
            encoded = await cast(
                Awaitable[object],
                self._redis.eval(
                    _CONSUME_LUA,
                    1,
                    self._key(challenge_id),
                ),
            )
        except Exception as exc:
            if self._require_redis or not self._settings.is_development:
                raise MobileIntegrityUnavailable(
                    "Integrity challenge persistence is unavailable"
                ) from exc
            return await self._local.consume(challenge_id)
        if encoded is None:
            return None
        if not isinstance(encoded, str):
            raise MobileIntegrityUnavailable("Integrity challenge storage returned invalid data")
        try:
            return MobileIntegrityChallenge.from_json(encoded)
        except (TypeError, ValueError) as exc:
            raise MobileIntegrityUnavailable("Integrity challenge storage is corrupt") from exc

    @staticmethod
    def _key(challenge_id: uuid.UUID) -> str:
        return f"mobile-integrity:v1:challenge:{challenge_id}"


_default_store: RedisMobileIntegrityChallengeStore | None = None


def get_mobile_integrity_challenge_store() -> MobileIntegrityChallengeStore:
    global _default_store
    if _default_store is None:
        _default_store = RedisMobileIntegrityChallengeStore()
    return _default_store


__all__ = [
    "InMemoryMobileIntegrityChallengeStore",
    "MobileIntegrityChallengeStore",
    "RedisMobileIntegrityChallengeStore",
    "get_mobile_integrity_challenge_store",
]
