"""Drain bounded native spreadsheet work before its request scope closes."""

import asyncio
from collections.abc import Callable
from functools import partial
from typing import Any, TypeVar

from anyio import CancelScope
from anyio.lowlevel import checkpoint_if_cancelled
from anyio.to_thread import run_sync

T = TypeVar("T")


async def run_tracker_work(operation: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    # Keep AnyIO's pre-start cancellation and shared thread limiter semantics.
    await checkpoint_if_cancelled()
    worker = asyncio.create_task(
        run_sync(partial(operation, *args, **kwargs), abandon_on_cancel=False)
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Task.cancel() bypasses AnyIO's cancellation shield. The request still
        # owns the worker's inputs and thread token until the native call exits.
        with CancelScope(shield=True):
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
        if not worker.cancelled():
            worker.exception()
        raise
