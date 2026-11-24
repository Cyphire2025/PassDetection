"""Owned Redis connection, bounded publication and subscriber recovery."""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from typing import cast

from redis.asyncio import Redis

from app.application.mobile.realtime_hints import MobileRealtimeHint
from app.core.logging.logger import get_logger
from app.infrastructure.mobile_realtime_contracts import (
    MobileRealtimeConfig,
    RealtimeRedis,
    RealtimeRedisPubSub,
    RealtimeStatus,
    RedisFactory,
)
from app.infrastructure.mobile_realtime_registry import RealtimeConnectionRegistry
from app.infrastructure.mobile_realtime_resources import _close_redis_resources, _complete_cleanup
from app.infrastructure.mobile_realtime_wire import (
    _CHANNEL,
    _LEASE_ACQUIRE_SCRIPT,
    _LEASE_RELEASE_SCRIPT,
    _RECONNECT_BASE_SECONDS,
    _RECONNECT_MAX_SECONDS,
    _parse_redis_hint,
)

logger = get_logger(__name__)


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


class RealtimeRedisTransport:
    def __init__(self, redis_factory: RedisFactory) -> None:
        self._redis_factory = redis_factory
        self._config: MobileRealtimeConfig | None = None
        self._status: RealtimeStatus = "stopped"
        self._redis: RealtimeRedis | None = None
        self._pubsub: RealtimeRedisPubSub | None = None
        self._redis_lock = asyncio.Lock()
        self._publish_queue: asyncio.Queue[MobileRealtimeHint] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._published = 0
        self._dropped = 0
        self._invalid_messages = 0
        self._redis_reconnect_attempts = 0
        self._redis_reconnect_successes = 0
        self._redis_publish_failures = 0
        self._redis_subscriber_failures = 0

    @property
    def config(self) -> MobileRealtimeConfig | None:
        return self._config

    @property
    def status(self) -> RealtimeStatus:
        return self._status

    def set_status(self, status: RealtimeStatus) -> None:
        self._status = status

    @property
    def redis(self) -> RealtimeRedis | None:
        return self._redis

    @property
    def accepting_connections(self) -> bool:
        return bool(self._config and self._config.enabled and self._status == "ready")

    def prepare(self, config: MobileRealtimeConfig) -> None:
        self._config = config
        if not config.enabled:
            self._status = "disabled"
            return
        self._status = "starting"
        self._loop = asyncio.get_running_loop()
        self._publish_queue = asyncio.Queue(maxsize=config.publish_queue_size)

    def discard_publication(self) -> None:
        self._publish_queue = None
        self._loop = None

    def finish_stop(self) -> None:
        self.discard_publication()
        if self._status != "disabled":
            self._status = "stopped"

    def snapshot(self) -> dict[str, int]:
        return {
            "published": self._published,
            "dropped": self._dropped,
            "invalid_messages": self._invalid_messages,
            "redis_reconnect_attempts": self._redis_reconnect_attempts,
            "redis_reconnect_successes": self._redis_reconnect_successes,
            "redis_publish_failures": self._redis_publish_failures,
            "redis_subscriber_failures": self._redis_subscriber_failures,
        }

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

    async def _connect_redis(self) -> None:
        config = self._config
        if config is None or not config.enabled:
            return
        async with self._redis_lock:
            await self._close_redis_unlocked()
            redis = self._redis_factory(config.redis_url)
            pubsub: RealtimeRedisPubSub | None = None
            try:
                await redis.ping()
                probe_id = str(uuid.uuid4())
                # Startup checks must not compete for the same one-slot lease
                # when several API workers connect or reconnect together.
                probe_key = f"{config.lease_namespace}:startup-probe:{probe_id}"
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
            except (Exception, asyncio.CancelledError):
                await _complete_cleanup(_close_redis_resources(pubsub, redis))
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
        await _complete_cleanup(_close_redis_resources(pubsub, redis))

    async def _subscriber_loop(self, registry: RealtimeConnectionRegistry) -> None:
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
            await registry.fanout(hint)

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
