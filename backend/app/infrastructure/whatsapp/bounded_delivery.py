"""Small bounded-concurrency primitive for independent delivery items."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")

DEFAULT_WHATSAPP_DELIVERY_CONCURRENCY = 4
MAX_WHATSAPP_DELIVERY_CONCURRENCY = 16


def bounded_delivery_concurrency(value: object) -> int:
    """Return a defensive worker limit even for malformed runtime settings."""

    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return DEFAULT_WHATSAPP_DELIVERY_CONCURRENCY
    try:
        parsed = int(value)
    except (ValueError, OverflowError):
        return DEFAULT_WHATSAPP_DELIVERY_CONCURRENCY
    return max(1, min(parsed, MAX_WHATSAPP_DELIVERY_CONCURRENCY))


async def run_bounded_delivery_items(
    items: Sequence[T],
    handler: Callable[[T], Awaitable[None]],
    *,
    concurrency: int,
) -> None:
    """Run every item with a fixed worker ceiling and failure isolation.

    A failed item does not cancel its siblings. Once all siblings have had a
    chance to finish, the first unexpected exception is raised so the durable
    task retry policy still sees infrastructure failures.
    """

    if not items:
        return
    worker_count = min(bounded_delivery_concurrency(concurrency), len(items))
    queue: asyncio.Queue[T] = asyncio.Queue()
    for item in items:
        queue.put_nowait(item)

    failures: list[Exception] = []

    async def worker() -> None:
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await handler(item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - re-raised after siblings finish.
                failures.append(exc)
            finally:
                queue.task_done()

    await asyncio.gather(*(worker() for _ in range(worker_count)))
    if failures:
        raise failures[0]
