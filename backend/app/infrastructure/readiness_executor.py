"""Deadline-bounded readiness work with a fixed process-local admission limit."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TypeVar, cast

_Result = TypeVar("_Result")


class ReadinessProbeCapacityError(RuntimeError):
    """All readiness slots are occupied by unfinished dependency work."""


class ReadinessProbeExecutor:
    """Share one unfinished job per named probe, including after HTTP timeout.

    Cancelling a thread's asyncio waiter cannot stop its socket call. Retain the
    real concurrent future until it finishes, so another request waits on the
    same operation instead of spawning another. Admission never exceeds the
    dedicated worker count; the executor cannot grow an unbounded work queue.
    """

    def __init__(self, *, max_workers: int = 8) -> None:
        self._capacity = max_workers
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="readiness")
        self._lock = threading.Lock()
        self._jobs: dict[str, tuple[Future[object], object]] = {}

    async def run(
        self,
        name: str,
        operation: Callable[[], _Result],
        *,
        timeout_seconds: float,
        configuration: object = None,
    ) -> _Result:
        with self._lock:
            self._jobs = {key: item for key, item in self._jobs.items() if not item[0].done()}
            existing = self._jobs.get(name)
            if existing is not None and existing[1] != configuration:
                raise ReadinessProbeCapacityError("Previous configuration probe is still running")
            if existing is None:
                if len(self._jobs) >= self._capacity:
                    raise ReadinessProbeCapacityError("Readiness work capacity reached")
                job = cast(Future[object], self._pool.submit(operation))
                self._jobs[name] = (job, configuration)
            else:
                job = existing[0]
        waiter = asyncio.wrap_future(job)
        # Observe late errors even when every HTTP waiter already timed out.
        waiter.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        result = await asyncio.wait_for(asyncio.shield(waiter), timeout=timeout_seconds)
        return cast(_Result, result)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


readiness_probe_executor = ReadinessProbeExecutor()
