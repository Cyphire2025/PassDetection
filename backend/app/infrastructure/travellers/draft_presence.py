"""Temporary processing presence, never document or identity authority.

One opaque key per active form expires in 30 minutes. Redis loss preserves
files until the fixed 24-hour draft expiry; cancel/resume remain transactional.
"""
import hashlib
import hmac
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator

from redis.asyncio import Redis

from app.core.config.settings import Settings, get_settings

PRESENCE_SECONDS = 30 * 60
CURSOR_KEY = "draft-image-cleanup:v1:cursor"


class DraftPresence:
    def __init__(self, client: Redis, settings: Settings):
        self.client, self.settings = client, settings

    def key(self, agency_id: uuid.UUID, draft_id: uuid.UUID) -> str:
        value = hmac.new(self.settings.app_secret_key.encode(),
            f"draft-presence\0{agency_id}\0{draft_id}".encode(), hashlib.sha256).hexdigest()
        return "draft-image-presence:v1:" + value

    async def touch(self, agency_id: uuid.UUID, draft_id: uuid.UUID) -> None:
        await self.client.set(self.key(agency_id, draft_id), "1", ex=PRESENCE_SECONDS)

    async def active(self, owners: list[tuple[uuid.UUID, uuid.UUID]]) -> set[uuid.UUID]:
        if not owners:
            return set()
        if len(owners) > 100:
            raise ValueError("draft_presence_batch_exceeded")
        values = await self.client.mget([self.key(*owner) for owner in owners])
        return {owner[1] for owner, value in zip(owners, values, strict=True) if value == "1"}

    async def cursor(self) -> tuple[datetime, uuid.UUID] | None:
        raw = await self.client.get(CURSOR_KEY)
        if raw is None:
            return None
        value = json.loads(raw)
        return datetime.fromisoformat(value[0]), uuid.UUID(value[1])

    async def advance(self, cursor: tuple[datetime, uuid.UUID] | None) -> None:
        if cursor is None:
            await self.client.delete(CURSOR_KEY)
        else:
            await self.client.set(CURSOR_KEY, json.dumps([cursor[0].isoformat(), str(cursor[1])]), ex=86400)


@asynccontextmanager
async def draft_presence(settings: Settings | None = None) -> AsyncIterator[DraftPresence]:
    settings = settings or get_settings()
    client = Redis.from_url(settings.redis.security_url, decode_responses=True,
        socket_timeout=1, socket_connect_timeout=1, max_connections=1)
    try:
        yield DraftPresence(client, settings)
    finally:
        await client.aclose()
