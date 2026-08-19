from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.application.mobile.realtime_authorization import MobileRealtimeAuthorization
from app.application.mobile.realtime_hints import MobileRealtimeHint
from app.infrastructure.mobile_realtime import (
    MobileRealtimeCapacityError,
    MobileRealtimeConfig,
    MobileRealtimeHub,
    _parse_redis_hint,
)


class _FakePubSub:
    def __init__(self) -> None:
        self.subscriptions: list[str] = []
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        self.subscriptions.extend(channels)

    async def get_message(self, **_kwargs: Any) -> None:
        await asyncio.sleep(60)

    async def aclose(self) -> None:
        self.closed = True


class _FakeLeaseState:
    def __init__(self) -> None:
        self.now_ms = 1_000
        self.leases: dict[str, dict[str, int]] = {}
        self.lock = asyncio.Lock()
        self.fail_eval = False

    def advance(self, milliseconds: int) -> None:
        self.now_ms += milliseconds


class _FakeRedis:
    def __init__(self, *, lease_state: _FakeLeaseState | None = None) -> None:
        self.pubsub_instance = _FakePubSub()
        self.lease_state = lease_state or _FakeLeaseState()
        self.published: list[tuple[str, str]] = []
        self.published_event = asyncio.Event()
        self.closed = False

    async def ping(self) -> bool:
        return True

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        self.published_event.set()
        return 1

    async def eval(self, script: str, _numkeys: int, *keys_and_args: object) -> object:
        state = self.lease_state
        if state.fail_eval:
            raise ConnectionError("capacity Redis unavailable")
        key = str(keys_and_args[0])
        async with state.lock:
            leases = state.leases.setdefault(key, {})
            expired = [lease_id for lease_id, expiry in leases.items() if expiry <= state.now_ms]
            for lease_id in expired:
                leases.pop(lease_id, None)
            if "lease-acquire" in script:
                lease_id = str(keys_and_args[1])
                limit = int(keys_and_args[2])
                ttl_ms = int(keys_and_args[3])
                if lease_id not in leases and len(leases) >= limit:
                    return 0
                leases[lease_id] = state.now_ms + ttl_ms
                return 1
            if "lease-renew" in script:
                ttl_ms = int(keys_and_args[1])
                missing: list[str] = []
                for raw_lease_id in keys_and_args[2:]:
                    lease_id = str(raw_lease_id)
                    if lease_id not in leases:
                        missing.append(lease_id)
                    else:
                        leases[lease_id] = state.now_ms + ttl_ms
                return missing
            if "lease-release" in script:
                removed = 0
                for raw_lease_id in keys_and_args[1:]:
                    if leases.pop(str(raw_lease_id), None) is not None:
                        removed += 1
                return removed
            raise AssertionError("unexpected Redis script")

    def pubsub(self) -> _FakePubSub:
        return self.pubsub_instance

    async def aclose(self) -> None:
        self.closed = True


def _config(**overrides: object) -> MobileRealtimeConfig:
    values: dict[str, object] = {
        "enabled": True,
        "require_redis": True,
        "redis_url": "redis://example.invalid/0",
        "heartbeat_seconds": 20,
        "idle_timeout_seconds": 65,
        "authorization_refresh_seconds": 30,
        "max_connections": 100,
        "max_authenticating_connections": 8,
        "global_max_connections": 100,
        "global_max_authenticating_connections": 8,
        "lease_ttl_seconds": 90,
        "lease_renew_interval_seconds": 20,
        "lease_namespace": "gc-mobile:realtime-capacity:test:v1",
        "max_connections_per_session": 2,
        "max_trips_per_connection": 100,
        "max_pending_trips_per_connection": 4,
        "publish_queue_size": 100,
        "send_timeout_seconds": 2.0,
    }
    values.update(overrides)
    return MobileRealtimeConfig(**values)  # type: ignore[arg-type]


def _authorization(
    *,
    agency_id: uuid.UUID,
    session_id: uuid.UUID,
    trip_ids: frozenset[uuid.UUID],
) -> MobileRealtimeAuthorization:
    principal_id = uuid.uuid4()
    return MobileRealtimeAuthorization(
        agency_id=agency_id,
        account_id=principal_id,
        principal_id=principal_id,
        principal_type="coordinator",
        session_id=session_id,
        session_generation=1,
        trip_ids=trip_ids,
    )


@pytest.mark.asyncio
async def test_hub_fanout_is_exact_tenant_and_trip_scoped_and_revocable() -> None:
    redis = _FakeRedis()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config())
    trip_id = uuid.uuid4()
    other_trip = uuid.uuid4()
    agency_id = uuid.uuid4()
    other_agency = uuid.uuid4()
    allowed = await hub.register(
        _authorization(
            agency_id=agency_id,
            session_id=uuid.uuid4(),
            trip_ids=frozenset({trip_id}),
        )
    )
    cross_tenant = await hub.register(
        _authorization(
            agency_id=other_agency,
            session_id=uuid.uuid4(),
            trip_ids=frozenset({trip_id}),
        )
    )
    wrong_trip = await hub.register(
        _authorization(
            agency_id=agency_id,
            session_id=uuid.uuid4(),
            trip_ids=frozenset({other_trip}),
        )
    )
    try:
        hint = MobileRealtimeHint(
            agency_id=agency_id,
            trip_id=trip_id,
            cursor=9,
            invalidation="roster",
        )
        assert await hub.fanout(hint) == 1
        assert await asyncio.wait_for(allowed.next_hint(), timeout=0.1) == hint

        revoked = MobileRealtimeAuthorization(
            agency_id=allowed.authorization.agency_id,
            account_id=allowed.authorization.account_id,
            principal_id=allowed.authorization.principal_id,
            principal_type=allowed.authorization.principal_type,
            session_id=allowed.authorization.session_id,
            session_generation=allowed.authorization.session_generation,
            trip_ids=frozenset(),
        )
        assert await hub.update_authorization(allowed, revoked) is True
        assert await hub.fanout(hint) == 0
        assert cross_tenant.trip_ids == frozenset({trip_id})
        assert wrong_trip.trip_ids == frozenset({other_trip})
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_duplicate_and_reordered_hints_are_coalesced_to_highest_cursor() -> None:
    redis = _FakeRedis()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config())
    agency_id = uuid.uuid4()
    trip_id = uuid.uuid4()
    connection = await hub.register(
        _authorization(
            agency_id=agency_id,
            session_id=uuid.uuid4(),
            trip_ids=frozenset({trip_id}),
        )
    )
    try:
        for cursor in (11, 9, 11, 14):
            await hub.fanout(
                MobileRealtimeHint(
                    agency_id=agency_id,
                    trip_id=trip_id,
                    cursor=cursor,
                    invalidation="itinerary",
                )
            )
        assert (await connection.next_hint()).cursor == 14
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_hub_uses_one_redis_subscriber_not_one_per_phone() -> None:
    created: list[_FakeRedis] = []

    def factory(_url: str) -> _FakeRedis:
        redis = _FakeRedis()
        created.append(redis)
        return redis

    hub = MobileRealtimeHub(redis_factory=factory)
    await hub.start(_config())
    agency_id = uuid.uuid4()
    for _ in range(20):
        await hub.register(
            _authorization(
                agency_id=agency_id,
                session_id=uuid.uuid4(),
                trip_ids=frozenset({uuid.uuid4()}),
            )
        )
    try:
        assert len(created) == 1
        assert created[0].pubsub_instance.subscriptions == ["gc-mobile:realtime:v1"]
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_post_commit_submission_is_handed_off_to_the_bounded_publish_queue() -> None:
    redis = _FakeRedis()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config())
    hint = MobileRealtimeHint(
        agency_id=uuid.uuid4(),
        trip_id=uuid.uuid4(),
        cursor=17,
        invalidation="documents",
    )
    try:
        hub.submit_post_commit((hint,))
        await asyncio.wait_for(redis.published_event.wait(), timeout=0.5)
        assert len(redis.published) == 1
        assert _parse_redis_hint(redis.published[0][1]) == hint
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_per_session_connection_limit_is_fail_closed() -> None:
    redis = _FakeRedis()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config(max_connections_per_session=1))
    session_id = uuid.uuid4()
    authorization = _authorization(
        agency_id=uuid.uuid4(),
        session_id=session_id,
        trip_ids=frozenset({uuid.uuid4()}),
    )
    try:
        await hub.register(authorization)
        with pytest.raises(MobileRealtimeCapacityError):
            await hub.register(authorization)
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_pre_authentication_database_work_is_bounded() -> None:
    redis = _FakeRedis()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config(max_authenticating_connections=1))
    try:
        reservation_id = await hub.begin_authorization()
        with pytest.raises(MobileRealtimeCapacityError):
            await hub.begin_authorization()
        assert hub.health()["authenticating"] == 1
        assert hub.health()["authentication_rejections"] == 1
        await hub.end_authorization(reservation_id)
        assert hub.health()["authenticating"] == 0
        reservation_id = await hub.begin_authorization()
        await hub.end_authorization(reservation_id)
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_connection_admission_is_atomic_across_hubs_and_release_is_immediate() -> None:
    state = _FakeLeaseState()
    first = MobileRealtimeHub(redis_factory=lambda _url: _FakeRedis(lease_state=state))
    second = MobileRealtimeHub(redis_factory=lambda _url: _FakeRedis(lease_state=state))
    config = _config(global_max_connections=1)
    await first.start(config)
    await second.start(config)
    authorization = _authorization(
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        trip_ids=frozenset({uuid.uuid4()}),
    )
    try:
        connection = await first.register(authorization)
        with pytest.raises(MobileRealtimeCapacityError, match="Global"):
            await second.register(
                _authorization(
                    agency_id=uuid.uuid4(),
                    session_id=uuid.uuid4(),
                    trip_ids=frozenset({uuid.uuid4()}),
                )
            )
        await first.unregister(connection)
        admitted_after_release = await second.register(
            _authorization(
                agency_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                trip_ids=frozenset({uuid.uuid4()}),
            )
        )
        assert admitted_after_release.close_code is None
    finally:
        await first.stop()
        await second.stop()


@pytest.mark.asyncio
async def test_authentication_admission_is_deployment_wide() -> None:
    state = _FakeLeaseState()
    first = MobileRealtimeHub(redis_factory=lambda _url: _FakeRedis(lease_state=state))
    second = MobileRealtimeHub(redis_factory=lambda _url: _FakeRedis(lease_state=state))
    config = _config(global_max_authenticating_connections=1)
    await first.start(config)
    await second.start(config)
    try:
        first_reservation = await first.begin_authorization()
        with pytest.raises(MobileRealtimeCapacityError, match="Global"):
            await second.begin_authorization()
        await first.end_authorization(first_reservation)
        second_reservation = await second.begin_authorization()
        await second.end_authorization(second_reservation)
    finally:
        await first.stop()
        await second.stop()


@pytest.mark.asyncio
async def test_expired_crashed_process_lease_is_reclaimed_on_next_admission() -> None:
    state = _FakeLeaseState()
    crashed = MobileRealtimeHub(redis_factory=lambda _url: _FakeRedis(lease_state=state))
    survivor = MobileRealtimeHub(redis_factory=lambda _url: _FakeRedis(lease_state=state))
    config = _config(
        global_max_connections=1,
        lease_ttl_seconds=1,
        lease_renew_interval_seconds=60,
    )
    await crashed.start(config)
    await survivor.start(config)
    try:
        await crashed.register(
            _authorization(
                agency_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                trip_ids=frozenset({uuid.uuid4()}),
            )
        )
        with pytest.raises(MobileRealtimeCapacityError):
            await survivor.register(
                _authorization(
                    agency_id=uuid.uuid4(),
                    session_id=uuid.uuid4(),
                    trip_ids=frozenset({uuid.uuid4()}),
                )
            )
        state.advance(1_001)
        recovered = await survivor.register(
            _authorization(
                agency_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                trip_ids=frozenset({uuid.uuid4()}),
            )
        )
        assert recovered.close_code is None
    finally:
        await crashed.stop()
        await survivor.stop()


@pytest.mark.asyncio
async def test_lease_renewal_failure_disconnects_active_sockets_and_fails_closed() -> None:
    state = _FakeLeaseState()
    hub = MobileRealtimeHub(redis_factory=lambda _url: _FakeRedis(lease_state=state))
    await hub.start(_config(lease_renew_interval_seconds=0.01))  # type: ignore[arg-type]
    connection = await hub.register(
        _authorization(
            agency_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            trip_ids=frozenset({uuid.uuid4()}),
        )
    )
    try:
        state.fail_eval = True
        await asyncio.sleep(0.05)
        assert connection.close_code == 1013
        assert hub.accepting_connections is False
        assert hub.health()["lease_renewal_failures"] >= 1
        assert hub.health()["lease_forced_disconnects"] == 1
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_slow_consumer_overflow_is_bounded_and_observable() -> None:
    redis = _FakeRedis()
    hub = MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config(max_pending_trips_per_connection=1))
    agency_id = uuid.uuid4()
    first_trip = uuid.uuid4()
    second_trip = uuid.uuid4()
    connection = await hub.register(
        _authorization(
            agency_id=agency_id,
            session_id=uuid.uuid4(),
            trip_ids=frozenset({first_trip, second_trip}),
        )
    )
    try:
        assert (
            await hub.fanout(
                MobileRealtimeHint(
                    agency_id=agency_id,
                    trip_id=first_trip,
                    cursor=1,
                    invalidation="all",
                )
            )
            == 1
        )
        assert (
            await hub.fanout(
                MobileRealtimeHint(
                    agency_id=agency_id,
                    trip_id=second_trip,
                    cursor=2,
                    invalidation="all",
                )
            )
            == 0
        )
        assert connection.close_code == 1013
        assert hub.health()["slow_consumer_disconnects"] == 1
    finally:
        await hub.stop()


@pytest.mark.asyncio
async def test_required_redis_failure_stops_startup_and_optional_mode_is_visible() -> None:
    def unavailable(_url: str) -> _FakeRedis:
        raise ConnectionError("redis://user:secret@private")

    required = MobileRealtimeHub(redis_factory=unavailable)
    with pytest.raises(RuntimeError, match="Redis is unavailable"):
        await required.start(_config(require_redis=True))
    assert required.readiness() == ("unreachable_required", False)

    optional = MobileRealtimeHub(redis_factory=unavailable)
    await optional.start(_config(require_redis=False))
    try:
        assert optional.readiness() == ("degraded_cursor_fallback", True)
        assert optional.accepting_connections is False
    finally:
        await optional.stop()


def test_redis_hint_parser_is_strict_and_pii_free() -> None:
    agency_id = uuid.uuid4()
    trip_id = uuid.uuid4()
    valid = '{"agency_id":"%s","cursor":7,"invalidation":"documents","trip_id":"%s","v":1}' % (
        agency_id,
        trip_id,
    )
    assert _parse_redis_hint(valid) == MobileRealtimeHint(
        agency_id=agency_id,
        trip_id=trip_id,
        cursor=7,
        invalidation="documents",
    )
    assert _parse_redis_hint(valid[:-1] + ',"name":"private"}') is None
