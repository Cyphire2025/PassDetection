"""Shared, fail-closed admission and weighted quotas across backend processes."""

import asyncio
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
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
if count >= tonumber(ARGV[2]) then return -2 end
redis.call('SET', KEYS[1], ARGV[1], 'EX', 240)
redis.call('ZADD', KEYS[3], now + 240, ARGV[1])
redis.call('EXPIRE', KEYS[3], 300)
redis.call('INCR', KEYS[2]); redis.call('EXPIRE', KEYS[2], 90000)
return count + 1
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


def _daily_key(user_id: UUID, operation: str) -> str:
    return f"assistant:v1:daily:{operation}:{user_id}:{datetime.now(UTC):%Y%m%d}"


async def reserve_images(user_id: UUID, *, count: int, limit: int) -> None:
    if not 1 <= count <= 4:
        raise AssistantError("image_count", "Create between one and four images at a time.", 422)
    redis = _redis()
    try:
        result = await _eval(
            redis, RESERVE_IMAGES, [_daily_key(user_id, "images")], [str(count), str(limit)]
        )
        if result < 0:
            raise AssistantError(
                "daily_image_limit", "Your daily image limit has been reached.", 429
            )
    except AssistantError:
        raise
    except Exception:
        raise AssistantError(
            "capacity_unavailable", "Image creation is temporarily unavailable. Please try again."
        ) from None
    finally:
        await redis.aclose()


@asynccontextmanager
async def assistant_admission(user_id: UUID, *, operation: str, limit: int) -> AsyncIterator[None]:
    redis = _redis()
    token = str(uuid4())
    lock = f"assistant:v1:active:{user_id}"
    try:
        result = await _eval(
            redis, ADMIT, [lock, _daily_key(user_id, operation), ACTIVE_KEY], [token, str(limit)]
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
            -2: ("daily_limit", "Your daily assistant limit has been reached."),
            -3: (
                "assistant_busy",
                "The assistant is helping other people. Please try again in a moment.",
            ),
        }[result]
        raise AssistantError(code, message, 429)
    try:
        async with asyncio.timeout(210):
            yield
    finally:
        try:
            await _eval(redis, RELEASE, [lock, ACTIVE_KEY], [token])
        except Exception:
            logger.warning("assistant_admission_release_failed")
        finally:
            await redis.aclose()
