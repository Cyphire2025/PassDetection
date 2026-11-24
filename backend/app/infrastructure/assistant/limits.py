"""Shared, fail-closed admission and weighted quotas across backend processes."""

import asyncio
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.application.assistant.contracts import AssistantError
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger

logger = get_logger(__name__)
ACTIVE_KEY = "assistant:v1:global-active"

ADMIT = """
local now = tonumber(redis.call('TIME')[1])
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now)
if redis.call('GET', KEYS[1]) then return -1 end
if redis.call('ZCARD', KEYS[3]) >= 3 then return -3 end
local count = tonumber(redis.call('GET', KEYS[2]) or '0')
local lease = tonumber(ARGV[3] or '240')
local distinct = ARGV[4] or ''
local counted = distinct ~= '' and redis.call('SISMEMBER', KEYS[4], distinct) == 1
if tonumber(ARGV[2]) == 0 or (not counted and count >= tonumber(ARGV[2])) then return -2 end
redis.call('SET', KEYS[1], ARGV[1], 'EX', lease)
redis.call('ZADD', KEYS[3], now + lease, ARGV[1])
if redis.call('TTL', KEYS[3]) < lease + 60 then redis.call('EXPIRE', KEYS[3], lease + 60) end
if counted then return 0 end
if distinct ~= '' then redis.call('SADD', KEYS[4], distinct); redis.call('EXPIRE', KEYS[4], 90000) end
redis.call('INCR', KEYS[2]); redis.call('EXPIRE', KEYS[2], 90000)
return count + 1
"""
CANCEL_VOICE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
if redis.call('SREM', KEYS[3], ARGV[2]) == 1 then
 local count = tonumber(redis.call('GET', KEYS[2]) or '0')
 if count > 0 then redis.call('DECR', KEYS[2]) end
end
return 1
"""
RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then redis.call('DEL', KEYS[1]) end
redis.call('ZREM', KEYS[2], ARGV[1]); return 1
"""
RESERVE_IMAGES = """
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
if count + tonumber(ARGV[1]) > tonumber(ARGV[2]) then return -1 end
local result = redis.call('INCRBY', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], 90000); return result
"""


def _redis() -> Redis:
    return cast(
        Redis,
        Redis.from_url(
            get_settings().redis.security_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            max_connections=2,
        ),
    )


async def _eval(redis: Redis, script: str, keys: list[str], arguments: list[str]) -> int:
    # redis-py's shared sync/async command annotation includes a synchronous branch.
    value = await cast(Awaitable[Any], redis.eval(script, len(keys), *keys, *arguments))
    return int(value)


def _daily_key(user_id: UUID, operation: str, now: datetime | None = None) -> str:
    return f"assistant:v1:daily:{operation}:{user_id}:{now or datetime.now(UTC):%Y%m%d}"


async def reserve_images(user_id: UUID, *, count: int, limit: int) -> None:
    if not 1 <= count <= 4:
        raise AssistantError("image_count", "Create between one and four images at a time.", 422)
    await reserve_daily_units(user_id, operation="images", count=count, limit=limit)


async def reserve_daily_units(user_id: UUID, *, operation: str, count: int, limit: int) -> None:
    if operation not in {"images", "chat"} or not 1 <= count <= 4:
        raise ValueError("Only bounded image or live text requests can reserve daily units")
    redis = _redis()
    try:
        result = await _eval(
            redis, RESERVE_IMAGES, [_daily_key(user_id, operation)], [str(count), str(limit)]
        )
        if result < 0:
            raise AssistantError(
                "daily_image_limit" if operation == "images" else "daily_limit",
                "Your daily image limit has been reached." if operation == "images" else quota_message("chat"), 429
            )
    except AssistantError:
        raise
    except Exception:
        raise AssistantError(
            "capacity_unavailable", "The assistant is temporarily unavailable. Please try again."
        ) from None
    finally:
        await redis.aclose()


@dataclass
class AdmissionReceipt:
    committed: bool = False

    def commit(self) -> None:
        self.committed = True


def quota_message(operation: str) -> str:
    label = {"voice_chats": "voice chat", "chat": "typed request", "uploads": "file upload", "speech": "speech request"}.get(operation, "assistant")
    return f"Your daily {label} limit has been reached. Check Usage limits in AI settings."


@asynccontextmanager
async def assistant_admission(user_id: UUID, *, operation: str, limit: int, timeout_seconds: int = 210, distinct_id: UUID | None = None) -> AsyncIterator[AdmissionReceipt]:
    if not 1 <= timeout_seconds <= 3600:
        raise ValueError("Assistant operation timeout must be bounded to one hour")
    if distinct_id is not None and operation != "voice_chats":
        raise ValueError("Distinct chat accounting is only valid for native voice")
    redis = _redis()
    token = str(uuid4())
    lock = f"assistant:v1:active:{user_id}"
    now = datetime.now(UTC)
    counter = _daily_key(user_id, operation, now)
    distinct = _daily_key(user_id, "voice_chat_ids", now)
    try:
        result = await _eval(
            redis, ADMIT, [lock, counter, ACTIVE_KEY, distinct], [token, str(limit), str(timeout_seconds + 30), str(distinct_id) if distinct_id else ""]
        )
    except Exception:
        await redis.aclose()
        raise AssistantError(
            "capacity_unavailable", "The assistant is temporarily unavailable. Please try again."
        ) from None
    if result < 0:
        await redis.aclose()
        code, message = {
            -1: ("request_in_progress", "Finish the current request first."),
            -2: ("daily_limit", quota_message(operation)),
            -3: (
                "assistant_busy",
                "The assistant is helping other people. Please try again in a moment.",
            ),
        }[result]
        raise AssistantError(code, message, 429)
    receipt = AdmissionReceipt()
    try:
        async with asyncio.timeout(timeout_seconds):
            yield receipt
    finally:
        try:
            if distinct_id and result > 0 and not receipt.committed:
                await _eval(redis, CANCEL_VOICE, [lock, counter, distinct], [token, str(distinct_id)])
        except Exception:
            logger.warning("assistant_voice_reservation_release_failed")
        finally:
            try:
                await _eval(redis, RELEASE, [lock, ACTIVE_KEY], [token])
            except Exception:
                logger.warning("assistant_admission_release_failed")
            finally:
                await redis.aclose()
