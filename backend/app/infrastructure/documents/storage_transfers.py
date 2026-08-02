"""Bounded, cancellation-safe helpers for sensitive document storage work."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")
DOCUMENT_STORAGE_WRITE_CONCURRENCY = 6


async def run_bounded_storage_operations(
    operations: Sequence[Callable[[], Awaitable[T]]],
    *,
    concurrency: int = DOCUMENT_STORAGE_WRITE_CONCURRENCY,
) -> list[T]:
    """Run storage writes concurrently, preserve order, and drain on failure."""

    if not operations:
        return []
    if concurrency < 1:
        raise ValueError("Storage concurrency must be positive")
    slots = asyncio.Semaphore(concurrency)

    async def run(operation: Callable[[], Awaitable[T]]) -> T:
        async with slots:
            return await operation()

    tasks = [asyncio.create_task(run(operation)) for operation in operations]
    batch = asyncio.gather(*tasks, return_exceptions=True)
    try:
        # Shield the batch so cancellation of the request does not abandon
        # boto threads that may still finish a PUT/COPY after cancellation.
        outcomes = list(await asyncio.shield(batch))
    except asyncio.CancelledError:
        # Drain every claimed write before the caller deletes all claimed keys.
        # Cancelling ``asyncio.to_thread`` cannot stop its underlying boto call
        # and can otherwise race cleanup, creating an orphan after deletion.
        await batch
        raise
    first_error = next((outcome for outcome in outcomes if isinstance(outcome, BaseException)), None)
    if first_error is not None:
        raise first_error
    return [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]


async def finish_cleanup_despite_cancellation(cleanup: Awaitable[None]) -> None:
    """Let owned-object cleanup finish before propagating request cancellation."""

    cleanup_task = asyncio.ensure_future(cleanup)
    try:
        await asyncio.shield(cleanup_task)
    except asyncio.CancelledError:
        # The caller remains cancelled, but a second await ensures its owned
        # sensitive objects are not abandoned before cancellation propagates.
        await cleanup_task
        raise
