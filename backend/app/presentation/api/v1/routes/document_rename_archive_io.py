"""Bounded archive reads/fetches with native worker draining."""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import AsyncGenerator
from typing import BinaryIO

from app.infrastructure.documents.storage_transfers import (
    run_bounded_storage_operations,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository


async def _stream_archive(
    archive: BinaryIO,
    *,
    release_admission: bool = False,
    admission: threading.BoundedSemaphore,
) -> AsyncGenerator[bytes, None]:
    try:
        while True:
            chunks = await run_bounded_storage_operations(
                [lambda: asyncio.to_thread(archive.read, 64 * 1024)], concurrency=1
            )
            chunk = chunks[0]
            if not chunk:
                break
            yield chunk
    finally:
        archive.close()
        if release_admission:
            admission.release()


async def _fetch_rename_archive_batch(
    storage: MinioStorageRepository,
    items: list[tuple[uuid.UUID, str, str, str, str]],
) -> list[bytes]:
    """Fetch one bounded window and drain every sibling on failure/cancellation."""

    tasks = [asyncio.create_task(storage.get_file(item[3])) for item in items]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
