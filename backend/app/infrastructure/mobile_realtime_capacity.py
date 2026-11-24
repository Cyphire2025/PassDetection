"""Two-phase local/global admission, lease renewal and fail-closed eviction."""

from __future__ import annotations

import asyncio
import uuid

from app.application.mobile.realtime_authorization import MobileRealtimeAuthorization
from app.core.logging.logger import get_logger
from app.infrastructure.mobile_realtime_connection import MobileRealtimeConnection
from app.infrastructure.mobile_realtime_contracts import MobileRealtimeCapacityError
from app.infrastructure.mobile_realtime_lease_store import RealtimeLeaseStore
from app.infrastructure.mobile_realtime_registry import RealtimeConnectionRegistry
from app.infrastructure.mobile_realtime_transport import RealtimeRedisTransport

logger = get_logger(__name__)


class RealtimeCapacityManager:
    def __init__(
        self,
        transport: RealtimeRedisTransport,
        registry: RealtimeConnectionRegistry,
        store: RealtimeLeaseStore,
    ) -> None:
        self._transport = transport
        self._registry = registry
        self._store = store
        self._lease_backend_failures = 0
        self._lease_renewal_failures = 0
        self._lease_forced_disconnects = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "lease_backend_failures": self._lease_backend_failures,
            "lease_renewal_failures": self._lease_renewal_failures,
            "lease_forced_disconnects": self._lease_forced_disconnects,
        }

    async def _acquire_lease(self, scope: str, lease_id: uuid.UUID, limit: int) -> bool:
        config = self._transport.config
        redis = self._transport.redis
        if config is None or redis is None or not self._transport.accepting_connections:
            raise MobileRealtimeCapacityError("Realtime capacity store is unavailable")
        try:
            return await self._store.acquire(config, redis, scope, lease_id, limit)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._handle_capacity_backend_failure(exc)
            raise MobileRealtimeCapacityError("Realtime capacity store is unavailable") from exc

    async def register(
        self,
        authorization: MobileRealtimeAuthorization,
    ) -> MobileRealtimeConnection:
        config = self._transport.config
        if config is None or not self._transport.accepting_connections:
            raise MobileRealtimeCapacityError("Realtime fanout is unavailable")
        connection = await self._registry.reserve_connection(authorization, config)

        try:
            acquired = await self._acquire_lease(
                "connections",
                connection.id,
                config.global_max_connections,
            )
        except asyncio.CancelledError:
            await self._registry._remove_connection(connection, close_code=1013)
            raise
        if not acquired:
            self._registry.reject_connection()
            await self._registry._remove_connection(connection, close_code=1013)
            raise MobileRealtimeCapacityError("Global realtime connection limit reached")

        if not await self._registry.activate_connection(connection):
            await self._release_owned_leases("connections", (connection.id,))
            raise MobileRealtimeCapacityError("Realtime fanout became unavailable")
        return connection

    async def begin_authorization(self) -> uuid.UUID:
        """Reserve bounded capacity before any JWT/session database query."""

        config = self._transport.config
        if config is None or not self._transport.accepting_connections:
            raise MobileRealtimeCapacityError("Realtime fanout is unavailable")
        reservation_id = await self._registry.reserve_authorization(config)

        try:
            acquired = await self._acquire_lease(
                "authenticating",
                reservation_id,
                config.global_max_authenticating_connections,
            )
        except asyncio.CancelledError:
            await self._registry._remove_authorization_reservation(reservation_id)
            raise
        if not acquired:
            self._registry.reject_authorization()
            await self._registry._remove_authorization_reservation(reservation_id)
            raise MobileRealtimeCapacityError("Global realtime authentication capacity reached")
        if not await self._registry.activate_authorization(reservation_id):
            await self._release_owned_leases("authenticating", (reservation_id,))
            raise MobileRealtimeCapacityError("Realtime fanout became unavailable")
        return reservation_id

    async def end_authorization(self, reservation_id: uuid.UUID) -> None:
        removed = await self._registry._remove_authorization_reservation(reservation_id)
        if removed:
            await self._release_owned_leases("authenticating", (reservation_id,))

    async def unregister(self, connection: MobileRealtimeConnection) -> None:
        leased = self._registry.connection_is_leased(connection.id)
        removed = await self._registry._remove_connection(connection, close_code=1000)
        if removed and leased:
            await self._release_owned_leases("connections", (connection.id,))

    async def _release_owned_leases(
        self,
        scope: str,
        lease_ids: tuple[uuid.UUID, ...],
    ) -> None:
        try:
            await self._store._release_leases(scope, lease_ids)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Expiry ultimately releases the departed socket, while active
            # sockets are disconnected because their ownership can no longer
            # be renewed safely.
            await self._handle_capacity_backend_failure(exc)

    async def _renew_capacity_leases_once(self) -> None:
        connection_ids, authorization_ids = await self._registry.lease_snapshot()
        missing_connections = await self._store._renew_leases("connections", connection_ids)
        missing_authorizations = await self._store._renew_leases(
            "authenticating",
            authorization_ids,
        )
        # A normal unregister may release a lease while a renewal is in flight.
        # Only leases that are both reported missing and still locally active
        # indicate that this process has lost its global admission ownership.
        if await self._registry.has_missing_active_leases(
            missing_connections, missing_authorizations
        ):
            raise RuntimeError("One or more active realtime capacity leases expired")

    async def _lease_renewal_loop(self) -> None:
        while True:
            config = self._transport.config
            if config is None:
                return
            await asyncio.sleep(config.lease_renew_interval_seconds)
            try:
                await self._renew_capacity_leases_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._lease_renewal_failures += 1
                await self._handle_capacity_backend_failure(exc)

    async def _handle_capacity_backend_failure(self, exc: Exception) -> None:
        self._lease_backend_failures += 1
        self._transport.set_status("degraded")
        logger.warning(
            "mobile_realtime_capacity_backend_failed",
            error_type=type(exc).__name__,
        )
        snapshot = await self._registry.clear()
        connections = snapshot.connections
        self._lease_forced_disconnects += len(connections)
        for connection in connections:
            connection.signal_close(1013)
        await self._transport._close_redis()
