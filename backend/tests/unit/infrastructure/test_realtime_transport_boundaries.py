"""Fault/recovery boundaries of the shared dashboard realtime transport."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import replace
from typing import Any

import pytest

from app.application.mobile.realtime_hints import MobileRealtimeHint
from app.infrastructure import mobile_realtime_transport
from app.infrastructure.mobile_realtime import MobileRealtimeHub
from tests.unit.infrastructure.test_mobile_realtime_hub import (
    _authorization,
    _config,
    _FakeLeaseState,
    _FakePubSub,
    _FakeRedis,
)


class _MessagePubSub(_FakePubSub):
    def __init__(self) -> None:
        super().__init__()
        self.messages: asyncio.Queue[object] = asyncio.Queue()
        self.reading = asyncio.Event()

    async def get_message(self, **_kwargs: Any) -> object:
        self.reading.set()
        result = await self.messages.get()
        if isinstance(result, Exception):
            raise result
        return result

    async def aclose(self) -> None:
        await super().aclose()
        self.messages.put_nowait(None)


@pytest.mark.asyncio
async def test_subscriber_read_failure_reconnects_and_delivers_without_logging_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = _FakeLeaseState()
    first, second = [_FakeRedis(lease_state=state) for _ in range(2)]
    before, after = _MessagePubSub(), _MessagePubSub()
    first.pubsub_instance, second.pubsub_instance = before, after
    clients = iter([first, second])
    hub = MobileRealtimeHub(redis_factory=lambda _url: next(clients))
    await hub.start(_config())
    hint = MobileRealtimeHint(uuid.uuid4(), uuid.uuid4(), 19, "attendance")
    connection = await hub.register(
        _authorization(
            agency_id=hint.agency_id, session_id=uuid.uuid4(), trip_ids=frozenset({hint.trip_id})
        )
    )
    try:
        before.messages.put_nowait(None)
        before.messages.put_nowait(ConnectionError("synthetic private Redis detail"))
        after.messages.put_nowait({"data": json.dumps(hint.redis_payload())})
        assert await asyncio.wait_for(connection.next_hint(), timeout=0.3) == hint
        assert first.closed and before.closed
        assert hub.accepting_connections is True
        assert hub.health()["redis_subscriber_failures"] == 1
        assert hub.health()["redis_reconnect_successes"] == 1
        assert "ConnectionError" in caplog.text
        assert "synthetic private Redis detail" not in caplog.text
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_publish_failure_is_lossy_then_next_commit_recovers() -> None:
    class _FailedPublishRedis(_FakeRedis):
        async def publish(self, channel: str, message: str) -> int:
            raise ConnectionError("synthetic publication failure")

    state = _FakeLeaseState()
    first, second = _FailedPublishRedis(lease_state=state), _FakeRedis(lease_state=state)
    first.pubsub_instance = _MessagePubSub()
    second_pubsub = _MessagePubSub()
    second.pubsub_instance = second_pubsub
    clients = iter([first, second])
    hub = MobileRealtimeHub(redis_factory=lambda _url: next(clients))
    await hub.start(_config())
    hint = MobileRealtimeHint(uuid.uuid4(), uuid.uuid4(), 19, "roster")
    try:
        hub.submit_post_commit((hint,))
        await asyncio.wait_for(second_pubsub.reading.wait(), timeout=0.3)
        assert hub.health()["redis_publish_failures"] == 1
        assert hub.health()["dropped"] == 1
        hub.submit_post_commit((replace(hint, cursor=20),))
        await asyncio.wait_for(second.published_event.wait(), timeout=0.3)
        assert json.loads(second.published[0][1]) == replace(hint, cursor=20).redis_payload()
        assert hub.health()["published"] == 1
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_optional_start_and_reconnect_failure_recover_with_bounded_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    pubsub = _MessagePubSub()
    redis.pubsub_instance = pubsub
    attempts = 0

    def factory(_url: str) -> _FakeRedis:
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise ConnectionError("synthetic unavailable transport")
        return redis

    monkeypatch.setattr(mobile_realtime_transport.random, "random", lambda: 0)
    hub = MobileRealtimeHub(redis_factory=factory)
    await hub.start(_config(require_redis=False))
    try:
        assert hub.readiness() == ("degraded_cursor_fallback", True)
        await asyncio.wait_for(pubsub.reading.wait(), timeout=0.3)
        assert attempts == 3
        assert hub.health()["redis_reconnect_attempts"] == 2
        assert hub.health()["redis_reconnect_successes"] == 1
        assert hub.readiness() == ("ok", True)
    finally:
        await hub.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_result", ["not-a-list", ["not-a-uuid"]])
async def test_malformed_renewal_result_closes_active_socket(invalid_result: object) -> None:
    class _InvalidRenewRedis(_FakeRedis):
        async def eval(self, script: str, numkeys: int, *args: object) -> object:
            if "lease-renew" in script:
                return invalid_result
            return await super().eval(script, numkeys, *args)

    redis = _InvalidRenewRedis()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config(lease_renew_interval_seconds=0.01))
    connection = await hub.register(
        _authorization(agency_id=uuid.uuid4(), session_id=uuid.uuid4(), trip_ids=frozenset())
    )
    try:
        # Socket writers wait on this actual close notification; no polling of private fields.
        from app.infrastructure.mobile_realtime import MobileRealtimeConnectionClosed

        with pytest.raises(MobileRealtimeConnectionClosed):
            await asyncio.wait_for(connection.next_hint(), timeout=0.3)
        assert connection.close_code == 1013
        assert hub.health()["lease_backend_failures"] >= 1
        assert hub.health()["connections"] == 0
    finally:
        await hub.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("agency_id", uuid.uuid4()),
        ("account_id", uuid.uuid4()),
        ("principal_id", uuid.uuid4()),
        ("principal_type", "dashboard"),
        ("session_id", uuid.uuid4()),
        ("session_generation", 2),
    ],
)
async def test_changed_authentication_boundary_rejects_existing_socket(
    field: str,
    value: object,
) -> None:
    redis = _FakeRedis()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config())
    authorization = _authorization(
        agency_id=uuid.uuid4(), session_id=uuid.uuid4(), trip_ids=frozenset({uuid.uuid4()})
    )
    connection = await hub.register(authorization)
    try:
        assert (
            await hub.update_authorization(connection, replace(authorization, **{field: value}))
            is False
        )
        assert connection.close_code == 4401
        assert (
            await hub.fanout(
                MobileRealtimeHint(
                    authorization.agency_id, next(iter(authorization.trip_ids)), 2, "all"
                )
            )
            == 0
        )
    finally:
        await hub.stop()
