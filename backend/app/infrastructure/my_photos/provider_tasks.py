"""Own started photo-provider siblings until the entire batch has stopped."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Sequence
from typing import TypeVar

from app.infrastructure.documents.storage_transfers import finish_cleanup_despite_cancellation

_Result = TypeVar("_Result")


async def gather_provider_results(operations: Sequence[Awaitable[_Result]]) -> list[_Result]:
    """Keep input order and the first error, cancelling then draining siblings.

    A coroutine cancellation cannot interrupt a running SDK thread. Its adapter
    owns that thread until exit; waiting here keeps the enclosing lease and
    retry decision from advancing while the previous batch still has effects.
    Callers retain their existing batch-size and concurrency limits.
    """
    tasks = [asyncio.ensure_future(operation) for operation in operations]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await finish_cleanup_despite_cancellation(asyncio.gather(*tasks, return_exceptions=True))
        raise
