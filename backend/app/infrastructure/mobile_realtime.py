"""Public shared realtime hub: lifecycle, admission facade and safe metrics."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from typing import Any

from app.application.mobile.realtime_authorization import MobileRealtimeAuthorization
from app.application.mobile.realtime_hints import (
    MobileRealtimeHint,
    register_mobile_realtime_publisher,
)
from app.core.config.settings import Settings
from app.core.logging.logger import get_logger
from app.infrastructure.mobile_realtime_capacity import RealtimeCapacityManager
from app.infrastructure.mobile_realtime_connection import MobileRealtimeConnection
from app.infrastructure.mobile_realtime_contracts import (
    MobileRealtimeCapacityError as MobileRealtimeCapacityError,
)
from app.infrastructure.mobile_realtime_contracts import MobileRealtimeConfig, RedisFactory
from app.infrastructure.mobile_realtime_contracts import (
    MobileRealtimeConnectionClosed as MobileRealtimeConnectionClosed,
)
from app.infrastructure.mobile_realtime_lease_store import RealtimeLeaseStore
from app.infrastructure.mobile_realtime_registry import RealtimeConnectionRegistry
from app.infrastructure.mobile_realtime_resources import _complete_cleanup
from app.infrastructure.mobile_realtime_transport import (
    RealtimeRedisTransport,
    _default_redis_factory,
)
from app.infrastructure.observability.metrics import metrics

logger = get_logger(__name__)


class MobileRealtimeHub:
    """Process-local fanout with deployment-wide Redis admission leases."""

    def __init__(self, *, redis_factory: RedisFactory = _default_redis_factory) -> None:
        self._transport = RealtimeRedisTransport(redis_factory)
        self._registry = RealtimeConnectionRegistry(self._transport)
        self._store = RealtimeLeaseStore(self._transport)
        self._capacity = RealtimeCapacityManager(self._transport, self._registry, self._store)
        self._subscriber_task: asyncio.Task[None] | None = None
        self._publisher_task: asyncio.Task[None] | None = None
        self._lease_task: asyncio.Task[None] | None = None
        self._publisher_unregister: Callable[[], None] | None = None

    @property
    def config(self) -> MobileRealtimeConfig | None:
        return self._transport.config

    @property
    def accepting_connections(self) -> bool:
        return self._transport.accepting_connections

    async def start(self, config: MobileRealtimeConfig) -> None:
        await self.stop()
        self._transport.prepare(config)
        if not config.enabled:
            return
        try:
            await self._transport._connect_redis()
        except asyncio.CancelledError:
            await _complete_cleanup(self.stop())
            raise
        except Exception as exc:
            self._transport.set_status("degraded")
            logger.error(
                "mobile_realtime_redis_startup_failed",
                error_type=type(exc).__name__,
                fallback="blocked" if config.require_redis else "cursor_only",
            )
            await self._transport._close_redis()
            if config.require_redis:
                self._transport.discard_publication()
                raise RuntimeError("Mobile realtime is enabled but Redis is unavailable") from exc
        self._publisher_unregister = register_mobile_realtime_publisher(self.submit_post_commit)
        self._subscriber_task = asyncio.create_task(
            self._transport._subscriber_loop(self._registry),
            name="mobile-realtime-subscriber",
        )
        self._publisher_task = asyncio.create_task(
            self._transport._publisher_loop(),
            name="mobile-realtime-publisher",
        )
        self._lease_task = asyncio.create_task(
            self._capacity._lease_renewal_loop(),
            name="mobile-realtime-capacity-leases",
        )

    async def stop(self) -> None:
        if self._publisher_unregister is not None:
            self._publisher_unregister()
            self._publisher_unregister = None
        tasks = [
            task
            for task in (self._subscriber_task, self._publisher_task, self._lease_task)
            if task is not None
        ]
        self._subscriber_task = None
        self._publisher_task = None
        self._lease_task = None
        for task in tasks:
            task.cancel()

        async def finish_stop() -> None:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.warning(
                        "mobile_realtime_background_task_failed",
                        error_type=type(result).__name__,
                    )
            await self._clear_and_close()

        await _complete_cleanup(finish_stop())

    async def _clear_and_close(self) -> None:
        snapshot = await self._registry.clear()
        for connection in snapshot.connections:
            connection.signal_close(1012)
        with contextlib.suppress(Exception):
            await self._store._release_leases("connections", snapshot.connection_lease_ids)
            await self._store._release_leases("authenticating", snapshot.authorization_lease_ids)
        await self._transport._close_redis()
        self._transport.finish_stop()

    def submit_post_commit(self, hints: tuple[MobileRealtimeHint, ...]) -> None:
        self._transport.submit_post_commit(hints)

    async def register(
        self, authorization: MobileRealtimeAuthorization
    ) -> MobileRealtimeConnection:
        return await self._capacity.register(authorization)

    async def begin_authorization(self) -> uuid.UUID:
        return await self._capacity.begin_authorization()

    async def end_authorization(self, reservation_id: uuid.UUID) -> None:
        await self._capacity.end_authorization(reservation_id)

    async def unregister(self, connection: MobileRealtimeConnection) -> None:
        await self._capacity.unregister(connection)

    async def update_authorization(
        self, connection: MobileRealtimeConnection, authorization: MobileRealtimeAuthorization
    ) -> bool:
        return await self._registry.update_authorization(connection, authorization)

    async def fanout(self, hint: MobileRealtimeHint) -> int:
        return await self._registry.fanout(hint)

    def health(self) -> dict[str, str | int | bool]:
        config = self.config
        transport = self._transport.snapshot()
        registry = self._registry.snapshot()
        capacity = self._capacity.snapshot()
        counters: dict[str, str | int | bool] = {
            **transport,
            **registry,
            **capacity,
            "dropped": transport["dropped"] + registry["dropped"],
        }
        if config is None:
            counters.pop("leased_connections")
            counters.pop("leased_authenticating")
            return {"status": "disabled", "enabled": False, "required": False, **counters}
        return {
            "status": self._transport.status,
            "enabled": config.enabled,
            "required": config.require_redis,
            **counters,
            "global_max_connections": config.global_max_connections,
            "global_max_authenticating": config.global_max_authenticating_connections,
        }

    def readiness(self) -> tuple[str, bool]:
        config = self.config
        if config is None or not config.enabled:
            return "disabled", True
        if self._transport.status == "ready":
            return "ok", True
        if config.require_redis:
            return "unreachable_required", False
        return "degraded_cursor_fallback", True


_mobile_realtime_hub = MobileRealtimeHub()


def _mobile_realtime_metrics_snapshot() -> dict[str, Any]:
    return _mobile_realtime_hub.health()


metrics.register_snapshot_provider("mobile_realtime", _mobile_realtime_metrics_snapshot)


def get_mobile_realtime_hub() -> MobileRealtimeHub:
    return _mobile_realtime_hub


async def start_mobile_realtime(settings: Settings) -> None:
    await _mobile_realtime_hub.start(MobileRealtimeConfig.from_settings(settings))


async def stop_mobile_realtime() -> None:
    await _mobile_realtime_hub.stop()


__all__ = [
    "MobileRealtimeCapacityError",
    "MobileRealtimeConfig",
    "MobileRealtimeConnection",
    "MobileRealtimeConnectionClosed",
    "MobileRealtimeHub",
    "get_mobile_realtime_hub",
    "start_mobile_realtime",
    "stop_mobile_realtime",
]
