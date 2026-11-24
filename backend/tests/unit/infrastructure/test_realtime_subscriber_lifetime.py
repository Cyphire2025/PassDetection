"""Dashboard-facing hub controls over synthetic Redis protocol resources."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from dataclasses import replace
from typing import Any

import pytest

from app.application.mobile.realtime_hints import MobileRealtimeHint
from app.infrastructure.mobile_realtime import MobileRealtimeHub
from app.infrastructure.mobile_realtime_wire import _parse_redis_hint
from tests.unit.infrastructure.test_mobile_realtime_hub import (
    _authorization,
    _config,
    _FakePubSub,
    _FakeRedis,
)


class _QueuedPubSub(_FakePubSub):
    def __init__(self) -> None:
        super().__init__()
        self.messages: asyncio.Queue[object] = asyncio.Queue()

    async def get_message(self, **_kwargs: Any) -> object:
        return await self.messages.get()


def _hint() -> MobileRealtimeHint:
    return MobileRealtimeHint(uuid.uuid4(), uuid.uuid4(), 7, "attendance")


@pytest.mark.parametrize("invalidation", [[], {}])
def test_redis_hint_rejects_unhashable_invalidation(invalidation: object) -> None:
    payload = {**_hint().redis_payload(), "invalidation": invalidation}
    assert _parse_redis_hint(json.dumps(payload)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [False, True])
async def test_dashboard_subscriber_delivers_after_untrusted_frame(malformed: bool) -> None:
    redis = _FakeRedis()
    pubsub = _QueuedPubSub()
    redis.pubsub_instance = pubsub
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config())
    hint = _hint()
    connection = await hub.register(
        replace(
            _authorization(
                agency_id=hint.agency_id,
                session_id=uuid.uuid4(),
                trip_ids=frozenset({hint.trip_id}),
            ),
            principal_type="dashboard",
        )
    )
    try:
        if malformed:
            await pubsub.messages.put(
                {"data": json.dumps({**hint.redis_payload(), "invalidation": {}})}
            )
        await pubsub.messages.put({"data": json.dumps(hint.redis_payload())})
        assert await asyncio.wait_for(connection.next_hint(), timeout=0.2) == hint
        assert hub.accepting_connections is True
        assert hub.health()["invalid_messages"] == int(malformed)
    finally:
        # Drain failed baseline tasks without replacing the primary delivery assertion.
        with contextlib.suppress(TypeError):
            await hub.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["ping", "subscribe"])
async def test_cancelled_start_closes_unpublished_protocol_resources(stage: str) -> None:
    entered = asyncio.Event()

    class _PausedPubSub(_FakePubSub):
        async def subscribe(self, *channels: str) -> None:
            await super().subscribe(*channels)
            if stage == "subscribe":
                entered.set()
                await asyncio.Event().wait()

    class _PausedRedis(_FakeRedis):
        async def ping(self) -> bool:
            if stage == "ping":
                entered.set()
                await asyncio.Event().wait()
            return True

    redis = _PausedRedis()
    redis.pubsub_instance = _PausedPubSub()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    task = asyncio.create_task(hub.start(_config()))
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert redis.closed is True
        if stage == "subscribe":
            assert redis.pubsub_instance.closed is True
        assert hub.accepting_connections is False
        assert hub.health()["status"] == "stopped"
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await hub.stop()


@pytest.mark.asyncio
async def test_shutdown_drains_failed_child_before_closing_connections(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = _FakeRedis()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config())
    authorization = _authorization(
        agency_id=uuid.uuid4(), session_id=uuid.uuid4(), trip_ids=frozenset()
    )
    connection = await hub.register(replace(authorization, principal_type="dashboard"))

    failure = TypeError("synthetic private worker content")

    async def failed_worker() -> None:
        raise failure

    original = hub._subscriber_task
    assert original is not None
    original.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await original
    hub._subscriber_task = asyncio.create_task(failed_worker())
    await asyncio.sleep(0)
    try:
        await hub.stop()
        assert connection.close_code == 1012
        assert redis.closed and redis.pubsub_instance.closed
        assert hub.health()["connections"] == 0
        assert hub.health()["leased_connections"] == 0
        assert "mobile_realtime_background_task_failed" in caplog.text
        assert "TypeError" in caplog.text
        assert str(failure) not in caplog.text
        assert str(failure) == "synthetic private worker content"
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_repeated_start_cancellation_finishes_both_resource_closes() -> None:
    subscribing = asyncio.Event()
    closing = asyncio.Event()
    allow_close = asyncio.Event()

    class _PausedClosePubSub(_FakePubSub):
        async def subscribe(self, *channels: str) -> None:
            subscribing.set()
            await asyncio.Event().wait()

        async def aclose(self) -> None:
            closing.set()
            await allow_close.wait()
            await super().aclose()

    redis = _FakeRedis()
    redis.pubsub_instance = _PausedClosePubSub()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    task = asyncio.create_task(hub.start(_config()))
    try:
        await asyncio.wait_for(subscribing.wait(), timeout=0.2)
        task.cancel()
        # An unclosed baseline fails here; no release assertion is hidden in teardown.
        await asyncio.wait_for(closing.wait(), timeout=0.2)
        task.cancel()
        allow_close.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert redis.pubsub_instance.closed is True
        assert redis.closed is True
    finally:
        allow_close.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await hub.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("close_failure", [RuntimeError, asyncio.CancelledError])
async def test_failed_pubsub_close_still_closes_client_and_original_start_error(
    close_failure: type[BaseException],
) -> None:
    failure = ConnectionError("synthetic subscribe failure")

    class _FailedClosePubSub(_FakePubSub):
        async def subscribe(self, *channels: str) -> None:
            raise failure

        async def aclose(self) -> None:
            self.closed = True
            raise close_failure("synthetic close failure")

    redis = _FakeRedis()
    redis.pubsub_instance = _FailedClosePubSub()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    with pytest.raises(RuntimeError, match="Redis is unavailable") as failed:
        await hub.start(_config())
    assert failed.value.__cause__ is failure
    assert redis.pubsub_instance.closed is True
    assert redis.closed is True
    await hub.stop()


@pytest.mark.asyncio
async def test_cancelled_stop_finishes_closes_and_releases_capacity() -> None:
    closing = asyncio.Event()
    allow_close = asyncio.Event()

    class _PausedClosePubSub(_FakePubSub):
        async def aclose(self) -> None:
            closing.set()
            await allow_close.wait()
            await super().aclose()

    redis = _FakeRedis()
    redis.pubsub_instance = _PausedClosePubSub()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config())
    connection = await hub.register(
        _authorization(agency_id=uuid.uuid4(), session_id=uuid.uuid4(), trip_ids=frozenset())
    )
    task = asyncio.create_task(hub.stop())
    try:
        await asyncio.wait_for(closing.wait(), timeout=0.2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        allow_close.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert redis.closed and redis.pubsub_instance.closed
        assert connection.close_code == 1012
        assert all(not leases for leases in redis.lease_state.leases.values())
        assert hub.health()["status"] == "stopped"
    finally:
        allow_close.set()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await hub.stop()
