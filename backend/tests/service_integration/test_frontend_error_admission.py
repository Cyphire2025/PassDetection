"""Actual shared Redis atomicity for the anonymous, metadata-only reporter."""

import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.presentation.api.v1.routes.frontend_errors import (
    _ADMIT,
    MAX_REPORTS_GLOBAL,
    MAX_REPORTS_PER_IP,
    REPORT_DEDUP_SECONDS,
    REPORT_WINDOW_SECONDS,
)

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated Redis required")]


async def test_independent_workers_share_ip_and_global_admission_without_quota_theft():
    # Unique expiring keys: no FLUSHDB or key deletion, even in the CI fixture.
    prefix = "{frontend-errors-ci-" + uuid4().hex + "}"
    url = os.environ["CI_FRONTEND_ERROR_REDIS_URL"]
    clients = [Redis.from_url(url, decode_responses=True) for _ in range(4)]
    async def admit(ip: str, event: str, worker: int = 0):
        return await clients[worker % 4].eval(_ADMIT, 3, prefix + ":global", prefix + ":ip:" + ip,
            prefix + ":event:" + ip + ":" + event, MAX_REPORTS_PER_IP, MAX_REPORTS_GLOBAL,
            REPORT_WINDOW_SECONDS, REPORT_DEDUP_SECONDS, event if len(event) == 36 else str(uuid4()))
    try:
        #100 simultaneous unique reports from oneIP admit only30. Rejected
        # attempts cannot exhaust the separate global report budget.
        results = await asyncio.gather(*(admit("one", str(i), i) for i in range(100)))
        assert sum(result[0] == 1 for result in results) == MAX_REPORTS_PER_IP
        assert sum(result[0] == -1 for result in results) == 70
        assert int(await clients[0].get(prefix + ":global")) == MAX_REPORTS_PER_IP
        assert 0 < await clients[0].ttl(prefix + ":ip:one") <= REPORT_WINDOW_SECONDS
        original = await admit("two", "duplicate")
        duplicate = await admit("two", "duplicate", 1)
        assert original[0] == 1 and duplicate == [0, original[1]]
        assert (await admit("three", "duplicate", 2))[0] == 1
        # Different IPs cannot suppress each other's matching fingerprint.
        results = await asyncio.gather(*(admit(f"peer-{i // 25}", str(i), i) for i in range(1100)))
        assert sum(result[0] == 1 for result in results) == MAX_REPORTS_GLOBAL - MAX_REPORTS_PER_IP - 2
        assert int(await clients[0].get(prefix + ":global")) == MAX_REPORTS_GLOBAL
        assert 0 < await clients[0].ttl(prefix + ":global") <= REPORT_WINDOW_SECONDS
        assert (await admit("new-peer", "new-event"))[0] == -1
        assert await clients[0].exists(prefix + ":ip:new-peer") == 0
    finally:
        await asyncio.gather(*(client.aclose() for client in clients))


async def test_stale_counter_without_expiry_is_repaired_without_sliding_the_window():
    prefix = "{frontend-errors-ci-" + uuid4().hex + "}"
    async with Redis.from_url(os.environ["CI_FRONTEND_ERROR_REDIS_URL"], decode_responses=True) as client:
        await client.set(prefix + ":global", 1)
        await client.set(prefix + ":ip", 1)
        async def admit(event):
            return await client.eval(_ADMIT, 3, prefix + ":global", prefix + ":ip", prefix + ":event:" + event,
                MAX_REPORTS_PER_IP, MAX_REPORTS_GLOBAL, REPORT_WINDOW_SECONDS, REPORT_DEDUP_SECONDS, event if len(event) == 36 else str(uuid4()))
        assert (await admit("first"))[0] == 1
        assert 0 < await client.ttl(prefix + ":global") <= REPORT_WINDOW_SECONDS
        assert 0 < await client.ttl(prefix + ":ip") <= REPORT_WINDOW_SECONDS
        await client.expire(prefix + ":global", 10)
        await client.expire(prefix + ":ip", 10)
        assert (await admit("second"))[0] == 1
        assert 0 < await client.ttl(prefix + ":global") <= 10
        assert 0 < await client.ttl(prefix + ":ip") <= 10
