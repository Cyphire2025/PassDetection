"""One Redis subscriber and bounded in-process fanout per API process."""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, cast

from redis.asyncio import Redis

from app.application.mobile.realtime_authorization import MobileRealtimeAuthorization
from app.application.mobile.realtime_hints import (
    MobileRealtimeHint,
    MobileRealtimeInvalidation,
    register_mobile_realtime_publisher,
)
from app.core.config.settings import Settings
from app.core.logging.logger import get_logger
from app.infrastructure.observability.metrics import metrics

_CHANNEL: Final = "gc-mobile:realtime:v1"
_MAX_REDIS_MESSAGE_BYTES: Final = 512
_RECONNECT_BASE_SECONDS: Final = 0.5
_RECONNECT_MAX_SECONDS: Final = 30.0
_LEASE_BATCH_SIZE: Final = 500
_LEASE_ACQUIRE_SCRIPT: Final = """
-- mobile-realtime-lease-acquire-v1
local now_parts = redis.call('TIME')
local now_ms = (now_parts[1] * 1000) + math.floor(now_parts[2] / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
if redis.call('ZSCORE', KEYS[1], ARGV[1]) then
  redis.call('ZADD', KEYS[1], now_ms + ARGV[3], ARGV[1])
  redis.call('PEXPIRE', KEYS[1], ARGV[3] * 2)
  return 1
end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
  return 0
end
redis.call('ZADD', KEYS[1], now_ms + ARGV[3], ARGV[1])
redis.call('PEXPIRE', KEYS[1], ARGV[3] * 2)
return 1
"""
_LEASE_RENEW_SCRIPT: Final = """
-- mobile-realtime-lease-renew-v1
local now_parts = redis.call('TIME')
local now_ms = (now_parts[1] * 1000) + math.floor(now_parts[2] / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
local missing = {}
for index = 2, #ARGV do
  if redis.call('ZSCORE', KEYS[1], ARGV[index]) then
    redis.call('ZADD', KEYS[1], now_ms + ARGV[1], ARGV[index])
  else
    table.insert(missing, ARGV[index])
  end
end
if redis.call('ZCARD', KEYS[1]) > 0 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1] * 2)
end
return missing
"""
_LEASE_RELEASE_SCRIPT: Final = """
-- mobile-realtime-lease-release-v1
if #ARGV == 0 then
  return 0
end
return redis.call('ZREM', KEYS[1], unpack(ARGV))
"""
_INVALIDATIONS: Final[frozenset[str]] = frozenset(
    {
        "all",
        "announcements",
        "attendance",
        "documents",
        "itinerary",
        "operations",
        "roster",
    }
)

logger = get_logger(__name__)


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


class MobileRealtimeConnection:
    """A bounded, trip-coalescing queue owned by one authenticated socket."""

    def __init__(
        self,
        *,
        authorization: MobileRealtimeAuthorization,
        maximum_pending_trips: int,
    ) -> None:
        self.id = uuid.uuid4()
        self.authorization = authorization
        self._maximum_pending_trips = maximum_pending_trips
        self._pending: dict[uuid.UUID, MobileRealtimeHint] = {}
        self._wake = asyncio.Event()
        self.close_code: int | None = None

    @property
    def trip_ids(self) -> frozenset[uuid.UUID]:
        return self.authorization.trip_ids

    def offer(self, hint: MobileRealtimeHint) -> bool:
        if self.close_code is not None:
            return False
        previous = self._pending.get(hint.trip_id)
        if previous is not None:
            self._pending[hint.trip_id] = MobileRealtimeHint(
                agency_id=hint.agency_id,
                trip_id=hint.trip_id,
                cursor=max(previous.cursor, hint.cursor),
                invalidation=(
                    previous.invalidation if previous.invalidation == hint.invalidation else "all"
                ),
            )
            self._wake.set()
            return True
        if len(self._pending) >= self._maximum_pending_trips:
            # Disconnecting a slow consumer is safer than allowing unbounded
            # memory growth. Its durable cursor reconciles on reconnect.
            self.signal_close(1013)
            return False
        self._pending[hint.trip_id] = hint
        self._wake.set()
        return True

    async def next_hint(self) -> MobileRealtimeHint:
        while True:
            if self.close_code is not None:
                raise MobileRealtimeConnectionClosed()
            if self._pending:
                trip_id = next(iter(self._pending))
                hint = self._pending.pop(trip_id)
                if not self._pending:
                    self._wake.clear()
                return hint
            self._wake.clear()
            await self._wake.wait()

    def signal_close(self, code: int) -> None:
        self.close_code = code
        self._pending.clear()
        self._wake.set()


def _default_redis_factory(url: str) -> RealtimeRedis:
    return cast(
        RealtimeRedis,
        Redis.from_url(
            url,
            decode_responses=True,
            health_check_interval=15,
            socket_connect_timeout=3.0,
            socket_timeout=5.0,
        ),
    )


def _parse_redis_hint(value: object) -> MobileRealtimeHint | None:
    if not isinstance(value, str) or len(value.encode("utf-8")) > _MAX_REDIS_MESSAGE_BYTES:
        return None
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or set(payload) != {
        "v",
        "agency_id",
        "trip_id",
        "cursor",
        "invalidation",
    }:
        return None
    cursor = payload.get("cursor")
    invalidation = payload.get("invalidation")
    if (
        payload.get("v") != 1
        or not isinstance(cursor, int)
        or isinstance(cursor, bool)
        or cursor < 1
        or cursor > (1 << 63) - 1
        or invalidation not in _INVALIDATIONS
    ):
        return None
    try:
        return MobileRealtimeHint(
            agency_id=uuid.UUID(str(payload.get("agency_id"))),
            trip_id=uuid.UUID(str(payload.get("trip_id"))),
            cursor=cursor,
            invalidation=cast(MobileRealtimeInvalidation, invalidation),
        )
    except (TypeError, ValueError):
        return None


class MobileRealtimeHub:
    """Process-local fanout with deployment-wide Redis admission leases."""

    def __init__(self, *, redis_factory: RedisFactory = _default_redis_factory) -> None:
        self._redis_factory = redis_factory
        self._config: MobileRealtimeConfig | None = None
        self._status: RealtimeStatus = "stopped"
        self._redis: RealtimeRedis | None = None
        self._pubsub: RealtimeRedisPubSub | None = None
        self._subscriber_task: asyncio.Task[None] | None = None
        self._publisher_task: asyncio.Task[None] | None = None
        self._lease_task: asyncio.Task[None] | None = None
        self._publish_queue: asyncio.Queue[MobileRealtimeHint] | None = None
        self._publisher_unregister: Callable[[], None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connection_lock = asyncio.Lock()
        self._redis_lock = asyncio.Lock()
        self._connections: dict[uuid.UUID, MobileRealtimeConnection] = {}
        self._trip_index: dict[tuple[uuid.UUID, uuid.UUID], set[uuid.UUID]] = {}
        self._session_connection_counts: Counter[uuid.UUID] = Counter()
        self._leased_connection_ids: set[uuid.UUID] = set()
        self._authorization_reservation_ids: set[uuid.UUID] = set()
        self._authorization_lease_ids: set[uuid.UUID] = set()
        self._authenticating = 0
        self._published = 0
        self._delivered = 0
        self._dropped = 0
        self._invalid_messages = 0
        self._authentication_rejections = 0
        self._connection_rejections = 0
        self._slow_consumer_disconnects = 0
        self._redis_reconnect_attempts = 0
        self._redis_reconnect_successes = 0
        self._redis_publish_failures = 0
        self._redis_subscriber_failures = 0
        self._lease_backend_failures = 0
        self._lease_renewal_failures = 0
        self._lease_forced_disconnects = 0

    @property
    def config(self) -> MobileRealtimeConfig | None:
        return self._config

    @property
    def accepting_connections(self) -> bool:
        return bool(self._config and self._config.enabled and self._status == "ready")

    async def start(self, config: MobileRealtimeConfig) -> None:
        await self.stop()
        self._config = config
        if not config.enabled:
            self._status = "disabled"
            return
        self._status = "starting"
        self._loop = asyncio.get_running_loop()
        self._publish_queue = asyncio.Queue(maxsize=config.publish_queue_size)
        try:
            await self._connect_redis()
        except Exception as exc:
            self._status = "degraded"
            logger.error(
                "mobile_realtime_redis_startup_failed",
                error_type=type(exc).__name__,
                fallback="blocked" if config.require_redis else "cursor_only",
            )
            await self._close_redis()
            if config.require_redis:
                self._publish_queue = None
                self._loop = None
                raise RuntimeError("Mobile realtime is enabled but Redis is unavailable") from exc
        self._publisher_unregister = register_mobile_realtime_publisher(self.submit_post_commit)
        self._subscriber_task = asyncio.create_task(
            self._subscriber_loop(),
            name="mobile-realtime-subscriber",
        )
        self._publisher_task = asyncio.create_task(
            self._publisher_loop(),
            name="mobile-realtime-publisher",
        )
        self._lease_task = asyncio.create_task(
            self._lease_renewal_loop(),
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
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        async with self._connection_lock:
            connections = tuple(self._connections.values())
            connection_lease_ids = tuple(self._leased_connection_ids)
            authorization_lease_ids = tuple(self._authorization_lease_ids)
            self._connections.clear()
            self._trip_index.clear()
            self._session_connection_counts.clear()
            self._leased_connection_ids.clear()
            self._authorization_reservation_ids.clear()
            self._authorization_lease_ids.clear()
            self._authenticating = 0
        for connection in connections:
            connection.signal_close(1012)
        with contextlib.suppress(Exception):
            await self._release_leases("connections", connection_lease_ids)
            await self._release_leases("authenticating", authorization_lease_ids)
        await self._close_redis()
        self._publish_queue = None
        self._loop = None
        if self._status != "disabled":
            self._status = "stopped"

    def submit_post_commit(self, hints: tuple[MobileRealtimeHint, ...]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            self._dropped += len(hints)
            return
        # Keep SQLAlchemy's synchronous after_commit callback O(1). Queueing
        # even a large coalesced batch occurs on the hub loop after the
        # transaction has returned to its caller.
        loop.call_soon_threadsafe(self._enqueue_hints, hints)

    def _enqueue_hints(self, hints: tuple[MobileRealtimeHint, ...]) -> None:
        queue = self._publish_queue
        if queue is None:
            self._dropped += len(hints)
            return
        for hint in hints:
            try:
                queue.put_nowait(hint)
            except asyncio.QueueFull:
                self._dropped += 1

    async def register(
        self,
        authorization: MobileRealtimeAuthorization,
    ) -> MobileRealtimeConnection:
        config = self._config
        if config is None or not self.accepting_connections:
            raise MobileRealtimeCapacityError("Realtime fanout is unavailable")
        connection = MobileRealtimeConnection(
            authorization=authorization,
            maximum_pending_trips=config.max_pending_trips_per_connection,
        )
        async with self._connection_lock:
            if len(self._connections) >= config.max_connections:
                self._connection_rejections += 1
                raise MobileRealtimeCapacityError("Realtime connection limit reached")
            if (
                self._session_connection_counts[authorization.session_id]
                >= config.max_connections_per_session
            ):
                self._connection_rejections += 1
                raise MobileRealtimeCapacityError("Realtime session connection limit reached")
            # Reserve locally before awaiting Redis so concurrent calls cannot
            # race past the process-local safety rails. The connection is not
            # indexed for fanout until its global lease succeeds.
            self._connections[connection.id] = connection
            self._session_connection_counts[authorization.session_id] += 1

        try:
            acquired = await self._acquire_lease(
                "connections",
                connection.id,
                config.global_max_connections,
            )
        except asyncio.CancelledError:
            await self._remove_connection(connection, close_code=1013)
            raise
        if not acquired:
            self._connection_rejections += 1
            await self._remove_connection(connection, close_code=1013)
            raise MobileRealtimeCapacityError("Global realtime connection limit reached")

        release_lease = False
        async with self._connection_lock:
            if not self.accepting_connections or connection.id not in self._connections:
                release_lease = True
            else:
                self._leased_connection_ids.add(connection.id)
                self._index_connection(connection)
        if release_lease:
            await self._release_owned_leases("connections", (connection.id,))
            raise MobileRealtimeCapacityError("Realtime fanout became unavailable")
        return connection

    async def begin_authorization(self) -> uuid.UUID:
        """Reserve bounded capacity before any JWT/session database query."""

        config = self._config
        if config is None or not self.accepting_connections:
            raise MobileRealtimeCapacityError("Realtime fanout is unavailable")
        async with self._connection_lock:
            if len(self._connections) >= config.max_connections:
                self._connection_rejections += 1
                raise MobileRealtimeCapacityError("Realtime connection limit reached")
            if self._authenticating >= config.max_authenticating_connections:
                self._authentication_rejections += 1
                raise MobileRealtimeCapacityError("Realtime authentication capacity reached")
            reservation_id = uuid.uuid4()
            self._authenticating += 1
            self._authorization_reservation_ids.add(reservation_id)

        try:
            acquired = await self._acquire_lease(
                "authenticating",
                reservation_id,
                config.global_max_authenticating_connections,
            )
        except asyncio.CancelledError:
            await self._remove_authorization_reservation(reservation_id)
            raise
        if not acquired:
            self._authentication_rejections += 1
            await self._remove_authorization_reservation(reservation_id)
            raise MobileRealtimeCapacityError("Global realtime authentication capacity reached")
        release_lease = False
        async with self._connection_lock:
            if (
                not self.accepting_connections
                or reservation_id not in self._authorization_reservation_ids
            ):
                release_lease = True
            else:
                self._authorization_lease_ids.add(reservation_id)
        if release_lease:
            await self._release_owned_leases("authenticating", (reservation_id,))
            raise MobileRealtimeCapacityError("Realtime fanout became unavailable")
        return reservation_id

    async def end_authorization(self, reservation_id: uuid.UUID) -> None:
        removed = await self._remove_authorization_reservation(reservation_id)
        if removed:
            await self._release_owned_leases("authenticating", (reservation_id,))

    async def _remove_authorization_reservation(self, reservation_id: uuid.UUID) -> bool:
        async with self._connection_lock:
            if reservation_id not in self._authorization_reservation_ids:
                return False
            self._authorization_reservation_ids.remove(reservation_id)
            self._authorization_lease_ids.discard(reservation_id)
            self._authenticating -= 1
            return True

    async def unregister(self, connection: MobileRealtimeConnection) -> None:
        leased = connection.id in self._leased_connection_ids
        removed = await self._remove_connection(connection, close_code=1000)
        if removed and leased:
            await self._release_owned_leases("connections", (connection.id,))

    async def _remove_connection(
        self,
        connection: MobileRealtimeConnection,
        *,
        close_code: int,
    ) -> bool:
        async with self._connection_lock:
            removed = self._connections.pop(connection.id, None)
            if removed is None:
                return False
            self._leased_connection_ids.discard(connection.id)
            self._deindex_connection(removed)
            session_id = removed.authorization.session_id
            self._session_connection_counts[session_id] -= 1
            if self._session_connection_counts[session_id] <= 0:
                del self._session_connection_counts[session_id]
        connection.signal_close(close_code)
        return True

    async def update_authorization(
        self,
        connection: MobileRealtimeConnection,
        authorization: MobileRealtimeAuthorization,
    ) -> bool:
        async with self._connection_lock:
            active = self._connections.get(connection.id)
            if active is None:
                return False
            if not active.authorization.same_authentication_boundary(authorization):
                active.signal_close(4401)
                return False
            self._deindex_connection(active)
            active.authorization = authorization
            self._index_connection(active)
            return True

    async def fanout(self, hint: MobileRealtimeHint) -> int:
        async with self._connection_lock:
            ids = tuple(self._trip_index.get((hint.agency_id, hint.trip_id), ()))
            connections = tuple(
                connection
                for connection_id in ids
                if (connection := self._connections.get(connection_id)) is not None
            )
        delivered = 0
        for connection in connections:
            was_open = connection.close_code is None
            if connection.offer(hint):
                delivered += 1
            else:
                self._dropped += 1
                if was_open and connection.close_code == 1013:
                    self._slow_consumer_disconnects += 1
        self._delivered += delivered
        return delivered

    def health(self) -> dict[str, str | int | bool]:
        config = self._config
        if config is None:
            return {
                "status": "disabled",
                "enabled": False,
                "required": False,
                "connections": 0,
                "authenticating": 0,
                "published": self._published,
                "delivered": self._delivered,
                "dropped": self._dropped,
                "invalid_messages": self._invalid_messages,
                "authentication_rejections": self._authentication_rejections,
                "connection_rejections": self._connection_rejections,
                "slow_consumer_disconnects": self._slow_consumer_disconnects,
                "redis_reconnect_attempts": self._redis_reconnect_attempts,
                "redis_reconnect_successes": self._redis_reconnect_successes,
                "redis_publish_failures": self._redis_publish_failures,
                "redis_subscriber_failures": self._redis_subscriber_failures,
                "lease_renewal_failures": self._lease_renewal_failures,
                "lease_forced_disconnects": self._lease_forced_disconnects,
                "lease_backend_failures": self._lease_backend_failures,
            }
        return {
            "status": self._status,
            "enabled": config.enabled,
            "required": config.require_redis,
            "connections": len(self._connections),
            "authenticating": self._authenticating,
            "leased_connections": len(self._leased_connection_ids),
            "leased_authenticating": len(self._authorization_lease_ids),
            "global_max_connections": config.global_max_connections,
            "global_max_authenticating": config.global_max_authenticating_connections,
            "published": self._published,
            "delivered": self._delivered,
            "dropped": self._dropped,
            "invalid_messages": self._invalid_messages,
            "authentication_rejections": self._authentication_rejections,
            "connection_rejections": self._connection_rejections,
            "slow_consumer_disconnects": self._slow_consumer_disconnects,
            "redis_reconnect_attempts": self._redis_reconnect_attempts,
            "redis_reconnect_successes": self._redis_reconnect_successes,
            "redis_publish_failures": self._redis_publish_failures,
            "redis_subscriber_failures": self._redis_subscriber_failures,
            "lease_renewal_failures": self._lease_renewal_failures,
            "lease_forced_disconnects": self._lease_forced_disconnects,
            "lease_backend_failures": self._lease_backend_failures,
        }

    def readiness(self) -> tuple[str, bool]:
        config = self._config
        if config is None or not config.enabled:
            return "disabled", True
        if self._status == "ready":
            return "ok", True
        if config.require_redis:
            return "unreachable_required", False
        return "degraded_cursor_fallback", True

    def _index_connection(self, connection: MobileRealtimeConnection) -> None:
        agency_id = connection.authorization.agency_id
        for trip_id in connection.trip_ids:
            self._trip_index.setdefault((agency_id, trip_id), set()).add(connection.id)

    def _deindex_connection(self, connection: MobileRealtimeConnection) -> None:
        agency_id = connection.authorization.agency_id
        for trip_id in connection.trip_ids:
            key = (agency_id, trip_id)
            ids = self._trip_index.get(key)
            if ids is None:
                continue
            ids.discard(connection.id)
            if not ids:
                self._trip_index.pop(key, None)

    def _lease_key(self, scope: str) -> str:
        config = self._config
        if config is None:
            raise RuntimeError("Realtime capacity configuration is unavailable")
        return f"{config.lease_namespace}:{scope}"

    async def _acquire_lease(self, scope: str, lease_id: uuid.UUID, limit: int) -> bool:
        config = self._config
        redis = self._redis
        if config is None or redis is None or not self.accepting_connections:
            raise MobileRealtimeCapacityError("Realtime capacity store is unavailable")
        try:
            result = await asyncio.wait_for(
                redis.eval(
                    _LEASE_ACQUIRE_SCRIPT,
                    1,
                    self._lease_key(scope),
                    str(lease_id),
                    limit,
                    config.lease_ttl_seconds * 1_000,
                ),
                timeout=config.send_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._handle_capacity_backend_failure(exc)
            raise MobileRealtimeCapacityError("Realtime capacity store is unavailable") from exc
        return result == 1

    async def _release_leases(self, scope: str, lease_ids: tuple[uuid.UUID, ...]) -> None:
        if not lease_ids:
            return
        config = self._config
        redis = self._redis
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

    async def _release_owned_leases(
        self,
        scope: str,
        lease_ids: tuple[uuid.UUID, ...],
    ) -> None:
        try:
            await self._release_leases(scope, lease_ids)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Expiry ultimately releases the departed socket, while active
            # sockets are disconnected because their ownership can no longer
            # be renewed safely.
            await self._handle_capacity_backend_failure(exc)

    async def _renew_leases(
        self,
        scope: str,
        lease_ids: tuple[uuid.UUID, ...],
    ) -> set[uuid.UUID]:
        if not lease_ids:
            return set()
        config = self._config
        redis = self._redis
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

    async def _renew_capacity_leases_once(self) -> None:
        async with self._connection_lock:
            connection_ids = tuple(self._leased_connection_ids)
            authorization_ids = tuple(self._authorization_lease_ids)
        missing_connections = await self._renew_leases("connections", connection_ids)
        missing_authorizations = await self._renew_leases(
            "authenticating",
            authorization_ids,
        )
        # A normal unregister may release a lease while a renewal is in flight.
        # Only leases that are both reported missing and still locally active
        # indicate that this process has lost its global admission ownership.
        async with self._connection_lock:
            active_missing_connections = missing_connections & self._leased_connection_ids
            active_missing_authorizations = missing_authorizations & self._authorization_lease_ids
        if active_missing_connections or active_missing_authorizations:
            raise RuntimeError("One or more active realtime capacity leases expired")

    async def _lease_renewal_loop(self) -> None:
        while True:
            config = self._config
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
        self._status = "degraded"
        logger.warning(
            "mobile_realtime_capacity_backend_failed",
            error_type=type(exc).__name__,
        )
        async with self._connection_lock:
            connections = tuple(self._connections.values())
            self._connections.clear()
            self._trip_index.clear()
            self._session_connection_counts.clear()
            self._leased_connection_ids.clear()
            self._authorization_reservation_ids.clear()
            self._authorization_lease_ids.clear()
            self._authenticating = 0
        self._lease_forced_disconnects += len(connections)
        for connection in connections:
            connection.signal_close(1013)
        await self._close_redis()

    async def _connect_redis(self) -> None:
        config = self._config
        if config is None or not config.enabled:
            return
        async with self._redis_lock:
            await self._close_redis_unlocked()
            redis = self._redis_factory(config.redis_url)
            try:
                await redis.ping()
                probe_key = f"{config.lease_namespace}:startup-probe"
                probe_id = str(uuid.uuid4())
                probe_result = await asyncio.wait_for(
                    redis.eval(
                        _LEASE_ACQUIRE_SCRIPT,
                        1,
                        probe_key,
                        probe_id,
                        1,
                        1_000,
                    ),
                    timeout=config.send_timeout_seconds,
                )
                if probe_result != 1:
                    raise RuntimeError("Realtime capacity store rejected its startup probe")
                await redis.eval(_LEASE_RELEASE_SCRIPT, 1, probe_key, probe_id)
                pubsub = redis.pubsub()
                await pubsub.subscribe(_CHANNEL)
            except Exception:
                with contextlib.suppress(Exception):
                    await redis.aclose()
                raise
            self._redis = redis
            self._pubsub = pubsub
            self._status = "ready"

    async def _close_redis(self) -> None:
        async with self._redis_lock:
            await self._close_redis_unlocked()

    async def _close_redis_unlocked(self) -> None:
        pubsub, redis = self._pubsub, self._redis
        self._pubsub = None
        self._redis = None
        if pubsub is not None:
            with contextlib.suppress(Exception):
                await pubsub.aclose()
        if redis is not None:
            with contextlib.suppress(Exception):
                await redis.aclose()

    async def _subscriber_loop(self) -> None:
        attempt = 0
        while True:
            if self._pubsub is None:
                self._redis_reconnect_attempts += 1
                try:
                    await self._connect_redis()
                    self._redis_reconnect_successes += 1
                    attempt = 0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._status = "degraded"
                    attempt += 1
                    logger.warning(
                        "mobile_realtime_redis_reconnect_failed",
                        error_type=type(exc).__name__,
                        attempt=attempt,
                    )
                    await asyncio.sleep(
                        random.random()
                        * min(
                            _RECONNECT_MAX_SECONDS,
                            _RECONNECT_BASE_SECONDS * (2 ** min(attempt, 10)),
                        )
                    )
                    continue
            pubsub = self._pubsub
            if pubsub is None:
                continue
            try:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._redis_subscriber_failures += 1
                logger.warning(
                    "mobile_realtime_redis_subscriber_failed",
                    error_type=type(exc).__name__,
                )
                self._status = "degraded"
                await self._close_redis()
                continue
            if not isinstance(message, dict):
                continue
            hint = _parse_redis_hint(message.get("data"))
            if hint is None:
                self._invalid_messages += 1
                continue
            await self.fanout(hint)

    async def _publisher_loop(self) -> None:
        queue = self._publish_queue
        if queue is None:
            return
        while True:
            hint = await queue.get()
            try:
                redis = self._redis
                if redis is None:
                    self._dropped += 1
                    continue
                payload = json.dumps(
                    hint.redis_payload(),
                    separators=(",", ":"),
                    sort_keys=True,
                )
                config = self._config
                timeout = config.send_timeout_seconds if config is not None else 5.0
                await asyncio.wait_for(redis.publish(_CHANNEL, payload), timeout=timeout)
                self._published += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._dropped += 1
                self._redis_publish_failures += 1
                self._status = "degraded"
                logger.warning(
                    "mobile_realtime_redis_publish_failed",
                    error_type=type(exc).__name__,
                )
                await self._close_redis()
            finally:
                queue.task_done()


_mobile_realtime_hub = MobileRealtimeHub()


def _mobile_realtime_metrics_snapshot() -> dict[str, Any]:
    return _mobile_realtime_hub.health()


metrics.register_snapshot_provider(
    "mobile_realtime",
    _mobile_realtime_metrics_snapshot,
)


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
