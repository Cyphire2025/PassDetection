"""Shared realtime configuration, Redis protocols and capacity errors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.config.settings import Settings


class RealtimeRedisPubSub(Protocol):
    async def subscribe(self, *channels: str) -> object: ...

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool,
        timeout: float,
    ) -> object: ...

    async def aclose(self) -> None: ...


class RealtimeRedis(Protocol):
    async def ping(self) -> object: ...

    async def publish(self, channel: str, message: str) -> object: ...

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...

    def pubsub(self) -> RealtimeRedisPubSub: ...

    async def aclose(self) -> None: ...


RedisFactory = Callable[[str], RealtimeRedis]


RealtimeStatus = Literal["disabled", "starting", "ready", "degraded", "stopped"]


@dataclass(frozen=True, slots=True)
class MobileRealtimeConfig:
    enabled: bool
    require_redis: bool
    redis_url: str
    heartbeat_seconds: int
    idle_timeout_seconds: int
    authorization_refresh_seconds: int
    max_connections: int
    max_authenticating_connections: int
    global_max_connections: int
    global_max_authenticating_connections: int
    lease_ttl_seconds: int
    lease_renew_interval_seconds: int
    lease_namespace: str
    max_connections_per_session: int
    max_trips_per_connection: int
    max_pending_trips_per_connection: int
    publish_queue_size: int
    send_timeout_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings) -> MobileRealtimeConfig:
        mobile = settings.mobile
        return cls(
            enabled=mobile.realtime_enabled,
            require_redis=mobile.realtime_require_redis,
            redis_url=settings.redis.realtime_url,
            heartbeat_seconds=mobile.realtime_heartbeat_seconds,
            idle_timeout_seconds=mobile.realtime_idle_timeout_seconds,
            authorization_refresh_seconds=mobile.realtime_authorization_refresh_seconds,
            max_connections=mobile.realtime_max_connections,
            max_authenticating_connections=(mobile.realtime_max_authenticating_connections),
            global_max_connections=mobile.realtime_global_max_connections,
            global_max_authenticating_connections=(
                mobile.realtime_global_max_authenticating_connections
            ),
            lease_ttl_seconds=mobile.realtime_lease_ttl_seconds,
            lease_renew_interval_seconds=mobile.realtime_lease_renew_interval_seconds,
            lease_namespace=f"gc-mobile:realtime-capacity:{settings.app_env}:v1",
            max_connections_per_session=mobile.realtime_max_connections_per_session,
            max_trips_per_connection=mobile.realtime_max_trips_per_connection,
            max_pending_trips_per_connection=(mobile.realtime_max_pending_trips_per_connection),
            publish_queue_size=mobile.realtime_publish_queue_size,
            send_timeout_seconds=mobile.realtime_send_timeout_seconds,
        )


class MobileRealtimeCapacityError(RuntimeError):
    """Raised before acceptance when a bounded connection limit is reached."""


class MobileRealtimeConnectionClosed(RuntimeError):
    """Wake a route writer when the hub has evicted its connection."""


class RealtimeAvailability(Protocol):
    @property
    def accepting_connections(self) -> bool: ...
