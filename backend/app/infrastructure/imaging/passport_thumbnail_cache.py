"""Bounded per-process cache for authenticated passport list thumbnails."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.infrastructure.imaging.passport_image_cropper import (
    RenderedPassportThumbnail,
)


@dataclass(slots=True)
class _KeyLock:
    lock: asyncio.Lock
    users: int = 0


class PassportThumbnailCache:
    """Deduplicate rendering and retain only a bounded number of thumbnail bytes."""

    def __init__(self, *, max_bytes: int, max_entries: int = 4_096) -> None:
        if max_bytes <= 0 or max_entries <= 0:
            raise ValueError("Thumbnail cache bounds must be positive.")
        self._max_bytes = max_bytes
        self._max_entries = max_entries
        self._items: OrderedDict[str, RenderedPassportThumbnail] = OrderedDict()
        self._total_bytes = 0
        self._state_lock = asyncio.Lock()
        self._key_locks: dict[str, _KeyLock] = {}

    async def get_or_create(
        self,
        key: str,
        creator: Callable[[], Awaitable[RenderedPassportThumbnail]],
    ) -> RenderedPassportThumbnail:
        cached = await self._get(key)
        if cached is not None:
            return cached

        async with self._state_lock:
            key_lock = self._key_locks.get(key)
            if key_lock is None:
                key_lock = _KeyLock(lock=asyncio.Lock())
                self._key_locks[key] = key_lock
            key_lock.users += 1

        try:
            async with key_lock.lock:
                cached = await self._get(key)
                if cached is not None:
                    return cached
                created = await creator()
                await self._store(key, created)
                return created
        finally:
            async with self._state_lock:
                key_lock.users -= 1
                if key_lock.users == 0 and self._key_locks.get(key) is key_lock:
                    self._key_locks.pop(key, None)

    async def clear(self) -> None:
        async with self._state_lock:
            self._items.clear()
            self._total_bytes = 0

    async def _get(self, key: str) -> RenderedPassportThumbnail | None:
        async with self._state_lock:
            item = self._items.get(key)
            if item is not None:
                self._items.move_to_end(key)
            return item

    async def _store(self, key: str, item: RenderedPassportThumbnail) -> None:
        item_size = len(item.content)
        if item_size > self._max_bytes:
            return
        async with self._state_lock:
            previous = self._items.pop(key, None)
            if previous is not None:
                self._total_bytes -= len(previous.content)
            self._items[key] = item
            self._total_bytes += item_size
            while self._total_bytes > self._max_bytes or len(self._items) > self._max_entries:
                _, evicted = self._items.popitem(last=False)
                self._total_bytes -= len(evicted.content)
