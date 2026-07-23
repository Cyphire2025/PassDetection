from __future__ import annotations

import asyncio
import contextvars

from app.infrastructure.celery_async_runtime import CeleryAsyncRuntime


def test_sequential_jobs_share_the_worker_process_event_loop() -> None:
    cleanup_loops: list[asyncio.AbstractEventLoop] = []
    loop_bound_future: asyncio.Future[str] | None = None

    async def cleanup() -> None:
        cleanup_loops.append(asyncio.get_running_loop())

    runtime = CeleryAsyncRuntime(cleanup=cleanup)

    async def current_loop() -> asyncio.AbstractEventLoop:
        nonlocal loop_bound_future
        loop_bound_future = asyncio.get_running_loop().create_future()
        return asyncio.get_running_loop()

    async def reuse_loop_bound_resource() -> tuple[asyncio.AbstractEventLoop, str]:
        assert loop_bound_future is not None
        asyncio.get_running_loop().call_soon(loop_bound_future.set_result, "ready")
        return asyncio.get_running_loop(), await loop_bound_future

    first_loop = runtime.run(current_loop())
    second_loop, result = runtime.run(reuse_loop_bound_resource())
    runtime.shutdown()

    assert second_loop is first_loop
    assert result == "ready"
    assert cleanup_loops == [first_loop]
    assert first_loop.is_closed()


def test_task_context_does_not_leak_between_sequential_jobs() -> None:
    marker: contextvars.ContextVar[str | None] = contextvars.ContextVar(
        "worker_task_marker",
        default=None,
    )
    runtime = CeleryAsyncRuntime(cleanup=_no_cleanup)

    async def set_marker() -> None:
        marker.set("first-job")

    async def read_marker() -> str | None:
        return marker.get()

    try:
        runtime.run(set_marker())
        assert runtime.run(read_marker()) is None
    finally:
        runtime.shutdown()


def test_shutdown_is_safe_before_the_runtime_is_initialized() -> None:
    cleanup_calls = 0

    async def cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1

    runtime = CeleryAsyncRuntime(cleanup=cleanup)

    runtime.shutdown()

    assert cleanup_calls == 0


async def _no_cleanup() -> None:
    return None
