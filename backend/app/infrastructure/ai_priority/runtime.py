"""Async lease maintenance shared by local and Celery runtimes."""

from __future__ import annotations

import asyncio
from types import TracebackType

from app.infrastructure.ai_priority.coordinator import AiPriorityCoordinator
from app.infrastructure.ai_priority.state import PriorityLease


class AiPriorityAdmissionDeferred(RuntimeError):
    def __init__(
        self,
        *,
        workload: str,
        reason: str,
        retry_after_ms: int,
    ) -> None:
        super().__init__(f"{workload} admission deferred: {reason}")
        self.workload = workload
        self.reason = reason
        self.retry_after_ms = max(1, retry_after_ms)


class MaintainPriorityLease:
    """Heartbeat a lease and release it idempotently on every exit path."""

    def __init__(
        self,
        coordinator: AiPriorityCoordinator,
        lease: PriorityLease,
    ) -> None:
        self._coordinator = coordinator
        self._lease = lease
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> MaintainPriorityLease:
        if self._lease.redis_available:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        await asyncio.to_thread(self._coordinator.release, self._lease)

    async def _heartbeat_loop(self) -> None:
        interval_seconds = max(0.05, self._lease.lease_ms / 3_000.0)
        while True:
            await asyncio.sleep(interval_seconds)
            await asyncio.to_thread(self._coordinator.heartbeat, self._lease)
