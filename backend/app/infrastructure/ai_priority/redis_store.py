"""Redis/Lua implementation of the global AI admission state machine."""

from __future__ import annotations

from typing import Any, Final

from redis import Redis

from app.infrastructure.ai_priority.state import (
    AtomicPriorityStore,
    QueueCounts,
    StoreMutation,
)

# Every mutation, lease cleanup, capacity check, and state transition is made
# inside one Redis script.  All keys use the same Redis Cluster hash tag.
_MUTATE_SCRIPT: Final[str] = r"""
local state_key = KEYS[1]
local generation_key = KEYS[2]
local extraction_waiting_key = KEYS[3]
local extraction_dispatching_key = KEYS[4]
local extraction_active_key = KEYS[5]
local verification_waiting_key = KEYS[6]
local verification_active_key = KEYS[7]
local last_extraction_activity_key = KEYS[8]

local operation = ARGV[1]
local member = ARGV[2]
local requested_generation = tonumber(ARGV[3]) or 0
local redis_time = redis.call("TIME")
local now_ms = (tonumber(redis_time[1]) * 1000)
  + math.floor(tonumber(redis_time[2]) / 1000)
local lease_ms = tonumber(ARGV[5])
local max_concurrency = tonumber(ARGV[6])
local quiet_period_ms = tonumber(ARGV[7])
local waiting_lease_ms = tonumber(ARGV[8])

local function parse_state(raw)
  if not raw then
    return nil, 0
  end
  local state, generation = string.match(raw, "^([^:]+):(%d+)$")
  return state, tonumber(generation) or 0
end

local function cleanup(key, expected_state, extraction_state)
  local expired = redis.call("ZRANGEBYSCORE", key, "-inf", now_ms)
  if #expired > 0 then
    for _, expired_member in ipairs(expired) do
      local current_state = parse_state(
        redis.call("HGET", state_key, expired_member)
      )
      if current_state == expected_state then
        redis.call("HDEL", state_key, expired_member)
      end
    end
    redis.call("ZREMRANGEBYSCORE", key, "-inf", now_ms)
    if extraction_state then
      redis.call("SET", last_extraction_activity_key, now_ms)
    end
  end
end

cleanup(extraction_waiting_key, "ew", true)
cleanup(extraction_dispatching_key, "ed", true)
cleanup(extraction_active_key, "ea", true)
cleanup(verification_waiting_key, "vw", false)
cleanup(verification_active_key, "va", false)

local function counts()
  return {
    redis.call("ZCARD", extraction_waiting_key),
    redis.call("ZCARD", extraction_dispatching_key),
    redis.call("ZCARD", extraction_active_key),
    redis.call("ZCARD", verification_waiting_key),
    redis.call("ZCARD", verification_active_key)
  }
end

local function result(code, generation, retry_after_ms)
  local current = counts()
  return {
    code,
    tostring(generation or 0),
    tostring(current[1]),
    tostring(current[2]),
    tostring(current[3]),
    tostring(current[4]),
    tostring(current[5]),
    tostring(retry_after_ms or 0)
  }
end

local function current()
  return parse_state(redis.call("HGET", state_key, member))
end

local function set_state(state, generation)
  redis.call("HSET", state_key, member, state .. ":" .. tostring(generation))
end

if operation == "snapshot" then
  return result("snapshot", 0, 0)
end

if operation == "register_extraction" then
  local state, generation = current()
  if state == "ew" then
    redis.call("ZADD", extraction_waiting_key, now_ms + lease_ms, member)
    return result("existing_waiting", generation, 0)
  end
  if state == "ed" then
    redis.call("ZADD", extraction_dispatching_key, now_ms + lease_ms, member)
    return result("existing_dispatching", generation, 0)
  end
  if state == "ea" then
    return result("existing_active", generation, 0)
  end
  local new_generation = redis.call("INCR", generation_key)
  set_state("ew", new_generation)
  redis.call("ZADD", extraction_waiting_key, now_ms + lease_ms, member)
  redis.call("SET", last_extraction_activity_key, now_ms)
  return result("registered", new_generation, 0)
end

if operation == "dispatch_extraction" then
  local state, generation = current()
  if generation ~= requested_generation then
    return result("stale", generation, 0)
  end
  if state == "ed" then
    redis.call("ZADD", extraction_dispatching_key, now_ms + lease_ms, member)
    return result("already_dispatching", generation, 0)
  end
  if state == "ea" then
    return result("already_active", generation, 0)
  end
  if state ~= "ew" then
    return result("missing", generation, 0)
  end
  redis.call("ZREM", extraction_waiting_key, member)
  redis.call("ZADD", extraction_dispatching_key, now_ms + lease_ms, member)
  set_state("ed", generation)
  return result("dispatched", generation, 0)
end

if operation == "start_extraction" then
  local state, generation = current()
  if generation ~= requested_generation then
    return result("stale", generation, 0)
  end
  if state == "ea" then
    return result("duplicate_active", generation, 0)
  end
  if state ~= "ew" and state ~= "ed" then
    return result("missing", generation, 0)
  end
  if redis.call("ZCARD", extraction_active_key) >= max_concurrency then
    redis.call("ZREM", extraction_dispatching_key, member)
    redis.call(
      "ZADD",
      extraction_waiting_key,
      now_ms + waiting_lease_ms,
      member
    )
    set_state("ew", generation)
    return result("deferred_capacity", generation, quiet_period_ms)
  end
  redis.call("ZREM", extraction_waiting_key, member)
  redis.call("ZREM", extraction_dispatching_key, member)
  redis.call("ZADD", extraction_active_key, now_ms + lease_ms, member)
  set_state("ea", generation)
  redis.call("SET", last_extraction_activity_key, now_ms)
  return result("admitted", generation, 0)
end

if operation == "heartbeat_extraction" then
  local state, generation = current()
  if state == "ea" and generation == requested_generation then
    redis.call("ZADD", extraction_active_key, now_ms + lease_ms, member)
    return result("heartbeat", generation, 0)
  end
  if generation ~= requested_generation then
    return result("stale", generation, 0)
  end
  return result("missing", generation, 0)
end

if operation == "release_extraction" then
  local state, generation = current()
  if not state then
    return result("released_idempotent", requested_generation, 0)
  end
  if generation ~= requested_generation then
    return result("stale", generation, 0)
  end
  redis.call("ZREM", extraction_waiting_key, member)
  redis.call("ZREM", extraction_dispatching_key, member)
  redis.call("ZREM", extraction_active_key, member)
  redis.call("HDEL", state_key, member)
  if state == "ea" then
    redis.call("SET", last_extraction_activity_key, now_ms)
  end
  return result("released", generation, 0)
end

if operation == "register_verification" then
  local state, generation = current()
  if state == "vw" then
    redis.call("ZADD", verification_waiting_key, now_ms + lease_ms, member)
    return result("existing_waiting", generation, 0)
  end
  if state == "va" then
    return result("existing_active", generation, 0)
  end
  local new_generation = redis.call("INCR", generation_key)
  set_state("vw", new_generation)
  redis.call("ZADD", verification_waiting_key, now_ms + lease_ms, member)
  return result("registered", new_generation, 0)
end

if operation == "start_verification" then
  local state, generation = current()
  if generation ~= requested_generation then
    return result("stale", generation, 0)
  end
  if state == "va" then
    return result("duplicate_active", generation, 0)
  end
  if state ~= "vw" then
    return result("missing", generation, 0)
  end
  local extraction_count = redis.call("ZCARD", extraction_waiting_key)
    + redis.call("ZCARD", extraction_dispatching_key)
    + redis.call("ZCARD", extraction_active_key)
  if extraction_count > 0 then
    redis.call(
      "ZADD",
      verification_waiting_key,
      now_ms + waiting_lease_ms,
      member
    )
    return result("deferred_extraction_priority", generation, quiet_period_ms)
  end
  local last_activity = tonumber(
    redis.call("GET", last_extraction_activity_key)
  ) or 0
  local quiet_remaining = quiet_period_ms - (now_ms - last_activity)
  if last_activity > 0 and quiet_remaining > 0 then
    redis.call(
      "ZADD",
      verification_waiting_key,
      now_ms + waiting_lease_ms,
      member
    )
    return result("deferred_quiet_period", generation, quiet_remaining)
  end
  if redis.call("ZCARD", verification_active_key) >= max_concurrency then
    redis.call(
      "ZADD",
      verification_waiting_key,
      now_ms + waiting_lease_ms,
      member
    )
    return result("deferred_capacity", generation, quiet_period_ms)
  end
  redis.call("ZREM", verification_waiting_key, member)
  redis.call("ZADD", verification_active_key, now_ms + lease_ms, member)
  set_state("va", generation)
  return result("admitted", generation, 0)
end

if operation == "heartbeat_verification" then
  local state, generation = current()
  if state == "va" and generation == requested_generation then
    redis.call("ZADD", verification_active_key, now_ms + lease_ms, member)
    return result("heartbeat", generation, 0)
  end
  if generation ~= requested_generation then
    return result("stale", generation, 0)
  end
  return result("missing", generation, 0)
end

if operation == "release_verification" then
  local state, generation = current()
  if not state then
    return result("released_idempotent", requested_generation, 0)
  end
  if generation ~= requested_generation then
    return result("stale", generation, 0)
  end
  redis.call("ZREM", verification_waiting_key, member)
  redis.call("ZREM", verification_active_key, member)
  redis.call("HDEL", state_key, member)
  return result("released", generation, 0)
end

return result("invalid_operation", 0, 0)
"""


class RedisPriorityStore(AtomicPriorityStore):
    """Execute the coordinator state machine against one shared Redis."""

    def __init__(
        self,
        redis_client: Any,
        *,
        namespace: str = "passdetection:{ai-priority}:v1",
    ) -> None:
        self._redis = redis_client
        self._keys = (
            f"{namespace}:state",
            f"{namespace}:generation",
            f"{namespace}:extraction:waiting",
            f"{namespace}:extraction:dispatching",
            f"{namespace}:extraction:active",
            f"{namespace}:verification:waiting",
            f"{namespace}:verification:active",
            f"{namespace}:extraction:last-activity-ms",
        )

    @classmethod
    def from_url(cls, redis_url: str) -> RedisPriorityStore:
        return cls(
            Redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=2.0,
            )
        )

    def mutate(
        self,
        *,
        operation: str,
        job_key: str,
        generation: int,
        now_ms: int,
        lease_ms: int,
        waiting_lease_ms: int,
        max_concurrency: int,
        quiet_period_ms: int,
    ) -> StoreMutation:
        raw = self._redis.eval(
            _MUTATE_SCRIPT,
            len(self._keys),
            *self._keys,
            operation,
            job_key,
            generation,
            now_ms,
            lease_ms,
            max_concurrency,
            quiet_period_ms,
            waiting_lease_ms,
        )
        if not isinstance(raw, (list, tuple)) or len(raw) != 8:
            raise RuntimeError("Redis returned an invalid AI priority response")
        decoded = [
            item.decode("utf-8") if isinstance(item, bytes) else str(item)
            for item in raw
        ]
        return StoreMutation(
            code=decoded[0],
            generation=int(decoded[1]),
            counts=QueueCounts(
                extraction_waiting=int(decoded[2]),
                extraction_dispatching=int(decoded[3]),
                extraction_active=int(decoded[4]),
                verification_waiting=int(decoded[5]),
                verification_active=int(decoded[6]),
            ),
            retry_after_ms=int(decoded[7]),
        )
