"""Drain owned workbook threads before closing or deleting their private files."""

import asyncio
from collections.abc import Callable
from typing import TypeVar

_Result = TypeVar("_Result")


async def run_export_native_work(operation: Callable[[], _Result]) -> _Result:
    worker = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        # The cancelled caller still owns cleanup. Retrieve any late native
        # exception and preserve cancellation after the worker has relinquished it.
        if not worker.cancelled():
            worker.exception()
        raise
