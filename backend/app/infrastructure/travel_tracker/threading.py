"""Drain bounded native spreadsheet work before its request scope closes."""

from collections.abc import Callable
from functools import partial
from typing import Any, TypeVar

from anyio.to_thread import run_sync

T = TypeVar("T")


async def run_tracker_work(operation: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    return await run_sync(partial(operation, *args, **kwargs), abandon_on_cancel=False)
