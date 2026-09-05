from __future__ import annotations

import asyncio
import threading

import pytest

from app.infrastructure.readiness_executor import (
    ReadinessProbeCapacityError,
    ReadinessProbeExecutor,
)


async def test_repeated_timeouts_reuse_unfinished_work_and_never_fill_an_unbounded_queue() -> None:
    executor = ReadinessProbeExecutor(max_workers=2)
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
        with pytest.raises(TimeoutError):
            await executor.run("storage", blocked_probe, timeout_seconds=0.01)
        with pytest.raises(ReadinessProbeCapacityError):
            await executor.run("overflow", blocked_probe, timeout_seconds=0.01)
        assert len(calls) == 2
        release.set()
        assert await executor.run("redis", blocked_probe, timeout_seconds=1, configuration="a")
    finally:
        release.set()
        executor.close()
