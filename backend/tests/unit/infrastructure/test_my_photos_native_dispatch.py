"""An SDK thread retains its caller's concurrency slot until it actually exits."""

import asyncio
import threading

import pytest

from app.infrastructure.my_photos.aws_client_runtime import _async_client_call


@pytest.mark.parametrize("late_failure", [False, True])
async def test_cancelled_dispatch_does_not_release_its_slot_while_sdk_thread_runs(late_failure):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    slot = asyncio.Semaphore(1)
    second_entered = asyncio.Event()

    def native():
        started.set()
        try:
            if not release.wait(5):
                raise AssertionError("Synthetic worker was never released")
            if late_failure:
                raise ValueError("synthetic late SDK failure")
            return {"ok": True}
        finally:
            finished.set()

    async def first():
        async with slot:
            return await _async_client_call(native)

    async def second():
        async with slot:
            second_entered.set()

    task = asyncio.create_task(first())
    waiter = None
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        waiter = asyncio.create_task(second())
        for _ in range(3):
            await asyncio.sleep(0)
        assert not second_entered.is_set(), "Cancelled SDK call released a live native worker's slot"
        assert not task.done()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "Repeated cancellation abandoned the SDK worker"
    finally:
        release.set()
        outcomes = await asyncio.gather(task, return_exceptions=True)
        if waiter is not None:
            await waiter
    assert isinstance(outcomes[0], asyncio.CancelledError)
    assert finished.is_set()


async def test_dispatch_preserves_arguments_result_and_uncancelled_failure():
    assert await _async_client_call(lambda first, *, second: (first, second), 4, second=9) == (4, 9)

    def fail():
        raise ValueError("synthetic immediate SDK failure")

    with pytest.raises(ValueError, match="synthetic immediate SDK failure"):
        await _async_client_call(fail)
