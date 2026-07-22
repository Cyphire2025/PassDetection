from __future__ import annotations

import asyncio

import pytest

from app.infrastructure.imaging.passport_image_cropper import (
    RenderedPassportThumbnail,
)
from app.infrastructure.imaging.passport_thumbnail_cache import PassportThumbnailCache


def _thumbnail(content: bytes) -> RenderedPassportThumbnail:
    return RenderedPassportThumbnail(
        content=content,
        content_type="image/jpeg",
        width=100,
        height=100,
    )


@pytest.mark.asyncio
async def test_concurrent_requests_render_one_thumbnail() -> None:
    cache = PassportThumbnailCache(max_bytes=1024)
    calls = 0

    async def create() -> RenderedPassportThumbnail:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return _thumbnail(b"same-thumbnail")

    results = await asyncio.gather(*(cache.get_or_create("same-key", create) for _ in range(20)))

    assert calls == 1
    assert all(item.content == b"same-thumbnail" for item in results)


@pytest.mark.asyncio
async def test_cache_evicts_oldest_bytes_within_its_hard_bound() -> None:
    cache = PassportThumbnailCache(max_bytes=10, max_entries=10)
    calls = {"first": 0, "second": 0}

    async def first() -> RenderedPassportThumbnail:
        calls["first"] += 1
        return _thumbnail(b"123456")

    async def second() -> RenderedPassportThumbnail:
        calls["second"] += 1
        return _thumbnail(b"abcdef")

    await cache.get_or_create("first", first)
    await cache.get_or_create("second", second)
    await cache.get_or_create("first", first)

    assert calls == {"first": 2, "second": 1}
