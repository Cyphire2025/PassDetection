"""Small shared roster cache with atomic global eviction and encrypted payloads."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import uuid
import zlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.application.use_cases.passports.submission_view import PreparedSubmissionView
from app.core.config.settings import get_settings
from app.infrastructure.passports.roster_cache_codec import decode, encode

TTL_SECONDS = 60
MAX_ENTRIES = 64
MAX_TOTAL_BYTES = 32 * 1024 * 1024
_STORE = """
local keys = redis.call('ZRANGE', KEYS[1], 0, -1)
local total = 0
local active = {}
for _, key in ipairs(keys) do
  local size = redis.call('STRLEN', key)
  if size == 0 or key == KEYS[2] then redis.call('ZREM', KEYS[1], key)
  else total = total + size; table.insert(active, {key, size}) end
end
local count = #active
local offset = 1
while count >= tonumber(ARGV[3]) or total + string.len(ARGV[1]) > tonumber(ARGV[4]) do
  local oldest = active[offset]
  if not oldest then return 0 end
  redis.call('DEL', oldest[1]); redis.call('ZREM', KEYS[1], oldest[1])
  total = total - oldest[2]; count = count - 1; offset = offset + 1
end
redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[2])
local now = redis.call('TIME')
redis.call('ZADD', KEYS[1], tonumber(now[1]) + tonumber(now[2])/1000000, KEYS[2])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]) + 5)
return 1
"""
_UNLOCK = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end"


class RosterCache:
    def __init__(self, client: Any = None, *, secret: str | None = None) -> None:
        settings = get_settings()
        secret = secret or settings.app_secret_key
        self.secret = hashlib.sha256(("roster-cache-v1:" + secret).encode()).digest()
        self.cipher = Fernet(base64.urlsafe_b64encode(self.secret))
        self.prefix = "passdetection:roster:v1:{" + hashlib.sha256(self.secret).hexdigest()[:20] + "}:"
        self.client: Any = client or Redis.from_url(settings.redis.cache_url, socket_connect_timeout=0.25,
            socket_timeout=0.25, max_connections=8, decode_responses=False)

    def identity(self, **values: object) -> str:
        return hmac.new(self.secret, json.dumps(values, sort_keys=True, default=str).encode(), hashlib.sha256).hexdigest()

    async def get(self, identity: str) -> PreparedSubmissionView | None:
        try:
            stored = await self.client.get(self.prefix + identity)
            if stored is not None:
                return await asyncio.to_thread(decode, stored, self.cipher, identity)
        except (RedisError, InvalidToken, ValueError, TypeError, KeyError, OverflowError, zlib.error):
            pass  # cache data never bypasses live database authorization
        return None

    async def put(self, identity: str, index: PreparedSubmissionView) -> None:
        stored = await asyncio.to_thread(encode, index, self.cipher, identity)
        if stored is None or len(stored) > MAX_TOTAL_BYTES:
            return
        try:
            await self.client.eval(_STORE, 2, self.prefix + "index", self.prefix + identity,
                                   stored, TTL_SECONDS, MAX_ENTRIES, MAX_TOTAL_BYTES)
        except RedisError:
            pass

    async def claim(self, identity: str) -> str | None:
        token = uuid.uuid4().hex
        try:
            if await self.client.set(self.prefix + "lock:" + identity, token, nx=True, ex=10):
                return token
        except RedisError:
            return "unavailable"
        return None

    async def release(self, identity: str, token: str) -> None:
        if token != "unavailable":
            try:
                await self.client.eval(_UNLOCK, 1, self.prefix + "lock:" + identity, token)
            except RedisError:
                pass

    async def close(self) -> None:
        try:
            await self.client.aclose()
        except RedisError:
            pass
