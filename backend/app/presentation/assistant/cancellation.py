"""Release upstream speech generation and its admission lease when the page disconnects."""

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from fastapi import Request

from app.application.assistant.contracts import AssistantError

T = TypeVar("T")


async def client_bound(request: Request, operation: Coroutine[Any, Any, T]) -> T:
    async def disconnected() -> None:
        while not await request.is_disconnected():
            await asyncio.sleep(0.25)

    work = asyncio.create_task(operation)
    watcher = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            return work.result()
        raise AssistantError("client_disconnected", "This voice request was stopped.", 499)
    finally:
        work.cancel()
        watcher.cancel()
        await asyncio.gather(work, watcher, return_exceptions=True)
