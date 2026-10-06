from __future__ import annotations

import asyncio
import threading

import pytest

from app.infrastructure.readiness_executor import (
    ReadinessProbeCapacityError,
    ReadinessProbeExecutor,
)


@pytest.mark.parametrize("max_workers", [2, 9])
async def test_repeated_timeouts_reuse_unfinished_work_and_never_fill_an_unbounded_queue(
    max_workers: int,
) -> None:
    executor = ReadinessProbeExecutor(max_workers=max_workers)
    release = threading.Event()
    calls = []

    def blocked_probe():
        calls.append(threading.get_ident())
        assert release.wait(3)
        return True

    try:
        for _ in range(3):
            results = await asyncio.gather(
                *[
                    executor.run("redis", blocked_probe, timeout_seconds=0.01, configuration="a")
                    for _ in range(20)
                ],
                return_exceptions=True,
            )
            assert all(isinstance(result, TimeoutError) for result in results)
        assert len(calls) == 1
        with pytest.raises(ReadinessProbeCapacityError):
            await executor.run("redis", blocked_probe, timeout_seconds=0.01, configuration="b")
        for index in range(1, max_workers):
            with pytest.raises(TimeoutError):
                await executor.run(f"storage-{index}", blocked_probe, timeout_seconds=0.01)
        with pytest.raises(ReadinessProbeCapacityError):
            await executor.run("overflow", blocked_probe, timeout_seconds=0.01)
        assert len(calls) == max_workers
        release.set()
        assert await executor.run("redis", blocked_probe, timeout_seconds=1, configuration="a")
    finally:
        release.set()
        executor.close()


def test_unfinished_work_can_be_awaited_from_a_new_event_loop() -> None:
    executor = ReadinessProbeExecutor()
    release = threading.Event()
    calls: list[int] = []

    def blocked_probe():
        calls.append(threading.get_ident())
        assert release.wait(3)
        return True

    async def resume_probe():
        asyncio.get_running_loop().call_soon(release.set)
        return await executor.run("redis", blocked_probe, timeout_seconds=1)

    try:
        with pytest.raises(TimeoutError):
            asyncio.run(executor.run("redis", blocked_probe, timeout_seconds=0.01))
        assert asyncio.run(resume_probe()) is True
        assert len(calls) == 1
    finally:
        release.set()
        executor.close()
