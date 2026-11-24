"""Atomic voice-chat accounting across independent workers on isolated Redis."""

import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.infrastructure.assistant.limits import ADMIT, CANCEL_VOICE, RELEASE

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(not os.getenv("ASSISTANT_TEST_REDIS_URL"), reason="isolated Redis required"),
]


async def test_distinct_chats_reconnect_at_limit_failures_refund_and_concurrent_retries():
    prefix = "assistant-usage-qa:" + uuid4().hex
    keys = [prefix + suffix for suffix in (":lock", ":count", ":active", ":chats")]
    clients = [
        Redis.from_url(os.environ["ASSISTANT_TEST_REDIS_URL"], decode_responses=True)
        for _ in range(3)
    ]
    first, second, third = (str(uuid4()) for _ in range(3))

    async def admit(chat, token, limit=2, worker=0):
        return await clients[worker].eval(ADMIT, 4, *keys, token, limit, 90, chat)

    async def release(token):
        await clients[0].eval(RELEASE, 2, keys[0], keys[2], token)

    try:
        assert await admit(first, "first") == 1
        await release("first")
        assert await admit(second, "second") == 2
        await release("second")
        assert await admit(first, "reconnect", worker=1) == 0
        assert int(await clients[0].get(keys[1])) == 2
        await release("reconnect")
        assert await admit(third, "over-limit", worker=2) == -2
        assert await admit(first, "disabled", limit=0) == -2
        assert await admit(third, "new-limit", limit=3) == 3
        # A setup failure rolls back only the new distinct chat reservation.
        assert (
            await clients[1].eval(CANCEL_VOICE, 3, keys[0], keys[1], keys[3], "wrong-lease", third)
            == 0
        )
        assert (
            await clients[1].eval(CANCEL_VOICE, 3, keys[0], keys[1], keys[3], "new-limit", third)
            == 1
        )
        await release("new-limit")
        assert int(await clients[0].get(keys[1])) == 2
        assert await clients[0].sismember(keys[3], third) == 0
        results = await asyncio.gather(
            *(admit(third, f"retry-{i}", limit=3, worker=i) for i in range(3))
        )
        assert sorted(results) == [-1, -1, 3]
        assert int(await clients[0].get(keys[1])) == 3
        assert await clients[0].scard(keys[3]) == 3
        assert 0 < await clients[0].ttl(keys[1]) <= 90000
        assert 0 < await clients[0].ttl(keys[3]) <= 90000
    finally:
        # Only fresh fixture-owned keys are touched; never FLUSHDB or production keys.
        for key in keys:
            await clients[0].expire(key, 30)
        await asyncio.gather(*(client.aclose() for client in clients))
