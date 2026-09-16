"""Overlapping worker startup against an explicitly isolated real Redis server."""

from __future__ import annotations

import asyncio
import os
import uuid
from urllib.parse import urlparse

import pytest
from redis.asyncio import Redis

from app.infrastructure.mobile_realtime import MobileRealtimeCapacityError, MobileRealtimeHub
from tests.unit.infrastructure.test_mobile_realtime_hub import _authorization, _config

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1" or not os.getenv("REALTIME_TEST_REDIS_URL"),
        reason="explicit isolated realtime startup Redis required",
    ),
]


@pytest.mark.asyncio
async def test_simultaneous_startup_works_and_real_global_capacity_stays_enforced():
    url = os.environ["REALTIME_TEST_REDIS_URL"]
    target = urlparse(url)
    assert target.scheme == "redis" and target.hostname.startswith("gc-realtime-startup-test-")
    assert target.port == 6379 and target.path == "/15"
    namespace = f"gc-mobile:realtime-capacity:isolated-test:{uuid.uuid4().hex}"
    arrived = 0
    all_acquired = asyncio.Event()

    class OverlappingRedis(Redis):
        async def eval(self, script, numkeys, *args):
            nonlocal arrived
            result = await super().eval(script, numkeys, *args)
            if "lease-acquire" in script and ":startup-probe" in str(args[0]):
                arrived += 1
                if arrived == 4:
                    all_acquired.set()
                await asyncio.wait_for(all_acquired.wait(), timeout=1)
            return result

    config = _config(
        redis_url=url,
        lease_namespace=namespace,
        global_max_connections=1,
        global_max_authenticating_connections=1,
    )
    hubs = [
        MobileRealtimeHub(redis_factory=lambda target_url: OverlappingRedis.from_url(target_url))
        for _ in range(4)
    ]
    try:
        results = await asyncio.gather(*(hub.start(config) for hub in hubs), return_exceptions=True)
        assert results == [None] * 4
        assert all(hub.accepting_connections for hub in hubs)
        authorization = _authorization(
            agency_id=uuid.uuid4(), session_id=uuid.uuid4(), trip_ids=frozenset({uuid.uuid4()})
        )
        await hubs[0].register(authorization)
        with pytest.raises(MobileRealtimeCapacityError):
            await hubs[1].register(authorization)
        reservation = await hubs[0].begin_authorization()
        try:
            with pytest.raises(MobileRealtimeCapacityError):
                await hubs[1].begin_authorization()
        finally:
            await hubs[0].end_authorization(reservation)
    finally:
        await asyncio.gather(*(hub.stop() for hub in hubs))
