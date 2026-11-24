"""Bounded atomic Redis capacity I/O, independent of socket eviction policy."""

from __future__ import annotations

import asyncio
import uuid

from app.infrastructure.mobile_realtime_contracts import MobileRealtimeConfig, RealtimeRedis
from app.infrastructure.mobile_realtime_transport import RealtimeRedisTransport
from app.infrastructure.mobile_realtime_wire import (
    _LEASE_ACQUIRE_SCRIPT,
    _LEASE_BATCH_SIZE,
    _LEASE_RELEASE_SCRIPT,
    _LEASE_RENEW_SCRIPT,
)


class RealtimeLeaseStore:
    def __init__(self, transport: RealtimeRedisTransport) -> None:
        self._transport = transport

    def _lease_key(self, scope: str) -> str:
        config = self._transport.config
        if config is None:
            raise RuntimeError("Realtime capacity configuration is unavailable")
        return f"{config.lease_namespace}:{scope}"

    async def acquire(
        self,
        config: MobileRealtimeConfig,
        redis: RealtimeRedis,
        scope: str,
        lease_id: uuid.UUID,
        limit: int,
    ) -> bool:
        result = await asyncio.wait_for(
            redis.eval(
                _LEASE_ACQUIRE_SCRIPT,
                1,
                self._lease_key(scope),
                str(lease_id),
                limit,
                config.lease_ttl_seconds * 1000,
            ),
            timeout=config.send_timeout_seconds,
        )
        return result == 1

    async def _release_leases(self, scope: str, lease_ids: tuple[uuid.UUID, ...]) -> None:
        if not lease_ids:
            return
        config = self._transport.config
        redis = self._transport.redis
        if config is None or redis is None:
            raise RuntimeError("Realtime capacity store is unavailable")
        for offset in range(0, len(lease_ids), _LEASE_BATCH_SIZE):
            batch = lease_ids[offset : offset + _LEASE_BATCH_SIZE]
            await asyncio.wait_for(
                redis.eval(
                    _LEASE_RELEASE_SCRIPT,
                    1,
                    self._lease_key(scope),
                    *(str(lease_id) for lease_id in batch),
                ),
                timeout=config.send_timeout_seconds,
            )

    async def _renew_leases(
        self,
        scope: str,
        lease_ids: tuple[uuid.UUID, ...],
    ) -> set[uuid.UUID]:
        if not lease_ids:
            return set()
        config = self._transport.config
        redis = self._transport.redis
        if config is None or redis is None:
            raise RuntimeError("Realtime capacity store is unavailable")
        missing: set[uuid.UUID] = set()
        for offset in range(0, len(lease_ids), _LEASE_BATCH_SIZE):
            batch = lease_ids[offset : offset + _LEASE_BATCH_SIZE]
            result = await asyncio.wait_for(
                redis.eval(
                    _LEASE_RENEW_SCRIPT,
                    1,
                    self._lease_key(scope),
                    config.lease_ttl_seconds * 1_000,
                    *(str(lease_id) for lease_id in batch),
                ),
                timeout=config.send_timeout_seconds,
            )
            if not isinstance(result, list):
                raise RuntimeError("Realtime capacity lease renewal returned an invalid result")
            try:
                missing.update(uuid.UUID(str(value)) for value in result)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "Realtime capacity lease renewal returned an invalid identifier"
                ) from exc
        return missing
