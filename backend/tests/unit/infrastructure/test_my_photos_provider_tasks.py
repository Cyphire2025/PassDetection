"""Photo-provider task batches retain ordering, cancellation and native ownership."""

import asyncio
import threading

import pytest

from app.infrastructure.my_photos.aws_client_runtime import _async_client_call
from app.infrastructure.my_photos.provider_tasks import gather_provider_results


async def test_batch_keeps_input_order_and_supports_empty_work():
    release = asyncio.Event()

    async def first():
        await release.wait()
        return "first"

    async def second():
        release.set()
        return "second"

    assert await gather_provider_results([]) == []
    assert await gather_provider_results([first(), second()]) == ["first", "second"]


@pytest.mark.parametrize("late_failure", [False, True])
async def test_repeated_batch_cancellation_drains_started_native_operation(late_failure):
    started = asyncio.Event()
    release, finished = threading.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def native():
        loop.call_soon_threadsafe(started.set)
        try:
            if not release.wait(5):
                raise AssertionError("Synthetic batch worker was never released")
            if late_failure:
                raise ValueError("Synthetic late provider failure")
            return "synthetic success"
        finally:
            finished.set()

    task = asyncio.create_task(gather_provider_results([_async_client_call(native)]))
    try:
        await asyncio.wait_for(started.wait(), 2)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done(), "Cancellation abandoned an owned native provider operation"
    finally:
        release.set()
        outcomes = await asyncio.gather(task, return_exceptions=True)
        assert await asyncio.to_thread(finished.wait, 2)
    assert isinstance(outcomes[0], asyncio.CancelledError)
