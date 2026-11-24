"""Exact atomic Redis lifecycle and bounded histogram scripts."""

from __future__ import annotations

from typing import Final

_QUEUE_LIFECYCLE_SCRIPT: Final[str] = r"""
local lifecycle_key = KEYS[1]
local queued_ms = tonumber(ARGV[1])
local lifecycle_seconds = tonumber(ARGV[2])

redis.call("HSETNX", lifecycle_key, "queued_ms", queued_ms)
redis.call("EXPIRE", lifecycle_key, lifecycle_seconds)
return true
"""


_OBSERVE_SCRIPT: Final[str] = r"""
local samples_key = KEYS[1]
local totals_key = KEYS[2]
local metric_name = ARGV[1]
local value = ARGV[2]
local max_samples = tonumber(ARGV[3])
local retention_seconds = tonumber(ARGV[4])

redis.call("HINCRBY", totals_key, metric_name, 1)
redis.call("EXPIRE", totals_key, retention_seconds)
redis.call("LPUSH", samples_key, value)
redis.call("LTRIM", samples_key, 0, max_samples - 1)
redis.call("EXPIRE", samples_key, retention_seconds)
return true
"""


_START_LIFECYCLE_SCRIPT: Final[str] = r"""
local lifecycle_key = KEYS[1]
local samples_key = KEYS[2]
local totals_key = KEYS[3]
local now_ms = tonumber(ARGV[1])
local lifecycle_seconds = tonumber(ARGV[2])
local retention_seconds = tonumber(ARGV[3])
local max_samples = tonumber(ARGV[4])
local metric_name = ARGV[5]

if redis.call("EXISTS", lifecycle_key) == 0 then
  return false
end
if redis.call("HSETNX", lifecycle_key, "started_ms", now_ms) == 0 then
  return false
end
redis.call("EXPIRE", lifecycle_key, lifecycle_seconds)
local queued_ms = tonumber(redis.call("HGET", lifecycle_key, "queued_ms"))
if not queued_ms then
  return false
end
local duration_ms = math.max(0, now_ms - queued_ms)
redis.call("HINCRBY", totals_key, metric_name, 1)
redis.call("EXPIRE", totals_key, retention_seconds)
redis.call("LPUSH", samples_key, tostring(duration_ms))
redis.call("LTRIM", samples_key, 0, max_samples - 1)
redis.call("EXPIRE", samples_key, retention_seconds)
return tostring(duration_ms)
"""


_COMPLETE_LIFECYCLE_SCRIPT: Final[str] = r"""
local lifecycle_key = KEYS[1]
local samples_key = KEYS[2]
local totals_key = KEYS[3]
local now_ms = tonumber(ARGV[1])
local retention_seconds = tonumber(ARGV[2])
local max_samples = tonumber(ARGV[3])
local metric_name = ARGV[4]

local queued_ms = tonumber(redis.call("HGET", lifecycle_key, "queued_ms"))
if not queued_ms then
  return false
end
if redis.call("HSETNX", lifecycle_key, "completed_ms", now_ms) == 0 then
  return false
end
local duration_ms = math.max(0, now_ms - queued_ms)
redis.call("HINCRBY", totals_key, metric_name, 1)
redis.call("EXPIRE", totals_key, retention_seconds)
redis.call("LPUSH", samples_key, tostring(duration_ms))
redis.call("LTRIM", samples_key, 0, max_samples - 1)
redis.call("EXPIRE", samples_key, retention_seconds)
redis.call("DEL", lifecycle_key)
return tostring(duration_ms)
"""
