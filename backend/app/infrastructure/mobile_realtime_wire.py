"""Exact bounded, PII-free Redis wire format and atomic capacity scripts."""

from __future__ import annotations

import json
import uuid
from typing import Final, cast

from app.application.mobile.realtime_hints import MobileRealtimeHint, MobileRealtimeInvalidation

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
        or not isinstance(invalidation, str)
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
