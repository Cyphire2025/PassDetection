"""Cancellation-safe completion of realtime-owned resource cleanup."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine
from typing import Any

from app.infrastructure.mobile_realtime_contracts import RealtimeRedis, RealtimeRedisPubSub


async def _complete_cleanup(cleanup: Coroutine[Any, Any, None]) -> None:
    """Finish resources we own before propagating a caller's cancellation."""

    task = asyncio.create_task(cleanup)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def _close_redis_resources(
    pubsub: RealtimeRedisPubSub | None,
    redis: RealtimeRedis | None,
) -> None:
    for resource in (pubsub, redis):
        if resource is not None:
            # These closes run in our shielded cleanup task. A close failure,
            # including a resource's own cancellation, must not skip its peer.
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await resource.aclose()
