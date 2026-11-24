"""Normal public hub flows across deferred Redis and registry transitions."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import uuid
from typing import get_type_hints

import pytest

from app.application.mobile.realtime_hints import MobileRealtimeHint
from app.infrastructure import mobile_realtime as public
from app.infrastructure.mobile_realtime_contracts import MobileRealtimeConfig
from tests.unit.infrastructure.test_mobile_realtime_hub import _authorization, _config, _FakeRedis


@pytest.mark.asyncio
async def test_reserved_connection_is_bounded_but_not_indexed_before_global_lease() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _DeferredRedis(_FakeRedis):
        async def eval(self, script: str, numkeys: int, *args: object) -> object:
            if "lease-acquire" in script and str(args[0]).endswith(":connections"):
                entered.set()
                await release.wait()
            return await super().eval(script, numkeys, *args)

    redis = _DeferredRedis()
    hub = public.MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config(max_connections_per_session=1))
    trip, agency = uuid.uuid4(), uuid.uuid4()
    authorization = _authorization(
        agency_id=agency, session_id=uuid.uuid4(), trip_ids=frozenset({trip})
    )
    pending = asyncio.create_task(hub.register(authorization))
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.2)
        assert hub.health()["connections"] == 1
        assert hub.health()["leased_connections"] == 0
        assert await hub.fanout(MobileRealtimeHint(agency, trip, 1, "attendance")) == 0
        with pytest.raises(public.MobileRealtimeCapacityError, match="session connection limit"):
            await hub.register(authorization)
        release.set()
        connection = await pending
        assert await hub.fanout(MobileRealtimeHint(agency, trip, 2, "attendance")) == 1
        assert (await connection.next_hint()).cursor == 2
        assert await hub.fanout(MobileRealtimeHint(uuid.uuid4(), trip, 3, "attendance")) == 0
        await hub.unregister(connection)
        assert all(not leases for leases in redis.lease_state.leases.values())
    finally:
        release.set()
        pending.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pending
        await hub.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["connections", "authenticating"])
async def test_cancelled_pending_admission_releases_local_slot(kind: str) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    pause = True

    class _DeferredRedis(_FakeRedis):
        async def eval(self, script: str, numkeys: int, *args: object) -> object:
            if pause and "lease-acquire" in script and str(args[0]).endswith(":" + kind):
                entered.set()
                await release.wait()
            return await super().eval(script, numkeys, *args)

    redis = _DeferredRedis()
    hub = public.MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config(max_connections=1, max_authenticating_connections=1))
    authorization = _authorization(
        agency_id=uuid.uuid4(), session_id=uuid.uuid4(), trip_ids=frozenset()
    )
    pending = asyncio.create_task(
        hub.register(authorization) if kind == "connections" else hub.begin_authorization()
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.2)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert hub.health()[kind] == 0
        pause = False
        if kind == "connections":
            connection = await hub.register(authorization)
            await hub.unregister(connection)
        else:
            reservation = await hub.begin_authorization()
            await hub.end_authorization(reservation)
        assert hub.health()[kind] == 0
        assert all(not leases for leases in redis.lease_state.leases.values())
    finally:
        release.set()
        pending.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pending
        await hub.stop()


@pytest.mark.asyncio
async def test_unregister_during_renewal_does_not_evict_other_active_session() -> None:
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    held = False

    class _DeferredRenewRedis(_FakeRedis):
        async def eval(self, script: str, numkeys: int, *args: object) -> object:
            nonlocal held
            if not held and "lease-renew" in script and str(args[0]).endswith(":connections"):
                held = True
                entered.set()
                await release.wait()
                result = await super().eval(script, numkeys, *args)
                finished.set()
                return result
            return await super().eval(script, numkeys, *args)

    redis = _DeferredRenewRedis()
    hub = public.MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config(lease_renew_interval_seconds=0.01))
    agency = uuid.uuid4()
    first, second = [
        await hub.register(
            _authorization(agency_id=agency, session_id=uuid.uuid4(), trip_ids=frozenset())
        )
        for _ in range(2)
    ]
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.2)
        await hub.unregister(first)
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=0.2)
        await asyncio.sleep(0)
        assert first.close_code == 1000
        assert second.close_code is None
        assert hub.health()["connections"] == 1
        assert hub.health()["lease_renewal_failures"] == 0
        assert hub.accepting_connections is True
    finally:
        release.set()
        await hub.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["connections", "authenticating"])
async def test_late_global_acquire_cannot_activate_after_shutdown(kind: str) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    class _LateAcquireRedis(_FakeRedis):
        async def eval(self, script: str, numkeys: int, *args: object) -> object:
            result = await super().eval(script, numkeys, *args)
            if "lease-acquire" in script and str(args[0]).endswith(":" + kind):
                entered.set()
                await release.wait()
            return result

    redis = _LateAcquireRedis()
    hub = public.MobileRealtimeHub(redis_factory=lambda _url: redis)
    await hub.start(_config())
    agency, trip = uuid.uuid4(), uuid.uuid4()
    authorization = _authorization(
        agency_id=agency, session_id=uuid.uuid4(), trip_ids=frozenset({trip})
    )
    pending = asyncio.create_task(
        hub.register(authorization) if kind == "connections" else hub.begin_authorization()
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.2)
        await hub.stop()
        release.set()
        with pytest.raises(public.MobileRealtimeCapacityError, match="became unavailable"):
            await pending
        assert hub.health()["connections"] == 0
        assert hub.health()["authenticating"] == 0
        assert hub.accepting_connections is False
        assert await hub.fanout(MobileRealtimeHint(agency, trip, 1, "attendance")) == 0
        # The uncertain acquire's finite lease expires, as before this composition.
        assert all(
            expiry == redis.lease_state.now_ms + 90_000
            for leases in redis.lease_state.leases.values()
            for expiry in leases.values()
        )
    finally:
        release.set()
        pending.cancel()
        with contextlib.suppress(asyncio.CancelledError, public.MobileRealtimeCapacityError):
            await pending
        await hub.stop()


def test_public_exports_aliases_defaults_and_annotations_remain_resolvable() -> None:
    assert public.__all__ == [
        "MobileRealtimeCapacityError",
        "MobileRealtimeConfig",
        "MobileRealtimeConnection",
        "MobileRealtimeConnectionClosed",
        "MobileRealtimeHub",
        "get_mobile_realtime_hub",
        "start_mobile_realtime",
        "stop_mobile_realtime",
    ]
    assert public.MobileRealtimeConfig is MobileRealtimeConfig
    assert public.get_mobile_realtime_hub() is public.get_mobile_realtime_hub()
    assert (
        get_type_hints(public.MobileRealtimeHub.register)["return"]
        is public.MobileRealtimeConnection
    )
    assert (
        get_type_hints(public.MobileRealtimeConfig.from_settings)["return"] is MobileRealtimeConfig
    )
    signature = inspect.signature(public.MobileRealtimeHub)
    assert signature.parameters["redis_factory"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["redis_factory"].default is public._default_redis_factory
    for name in [
        "start",
        "stop",
        "begin_authorization",
        "end_authorization",
        "unregister",
        "update_authorization",
        "fanout",
        "health",
        "readiness",
    ]:
        assert get_type_hints(getattr(public.MobileRealtimeHub, name))
