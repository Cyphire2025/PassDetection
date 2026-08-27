"""Atomic Redis counter primitives shared by authentication limiters."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis

_INCREMENT_WITH_TTL_SCRIPT = """
local key = KEYS[1]
local ttl_seconds = tonumber(ARGV[1])

local count = redis.call('INCR', key)
local current_ttl = redis.call('TTL', key)
if current_ttl < 0 then
    redis.call('EXPIRE', key, ttl_seconds)
end

return count
"""


async def increment_with_ttl_atomic(
    redis: Redis,
    *,
    key: str,
    ttl_seconds: int,
) -> int:
    """Increment ``key`` and ensure it has a TTL in one Redis operation.

    A positive existing TTL is deliberately left untouched so the counter
    remains a fixed window. Missing TTLs are repaired inside the same script,
    including keys left behind by a pre-atomic implementation.
    """

    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    result: object = await cast(
        Awaitable[object],
        redis.eval(_INCREMENT_WITH_TTL_SCRIPT, 1, key, str(ttl_seconds)),
    )
    if isinstance(result, bool):
        raise TypeError("Redis counter returned an invalid boolean result")
    if isinstance(result, int):
        return result
    if isinstance(result, (bytes, str)):
        try:
            return int(result)
        except ValueError:
            pass
    raise TypeError("Redis counter returned an invalid result type")
