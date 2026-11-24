"""Native failures and cancellation retain resource ownership until completion."""

import asyncio
import threading

import pytest

from app.infrastructure.travellers.company_export_native_work import run_export_native_work


async def test_uncancelled_native_error_reaches_the_existing_failure_boundary():
    def fail():
        raise ValueError("synthetic native failure")

    with pytest.raises(ValueError, match="synthetic native failure"):
        await run_export_native_work(fail)


async def test_cancelled_native_error_is_drained_before_cancellation_returns():
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def fail_later():
        started.set()
        try:
            if not release.wait(timeout=5):
                raise AssertionError("Synthetic native worker was never released")
            raise ValueError("synthetic late native failure")
        finally:
            finished.set()

    task = asyncio.create_task(run_export_native_work(fail_later))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
    assert finished.is_set()
