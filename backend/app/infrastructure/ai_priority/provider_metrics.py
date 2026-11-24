"""Offload synchronous shared telemetry from async provider request handlers."""

import asyncio

from app.infrastructure.ai_priority.metrics import AiPriorityMetrics
from app.infrastructure.ai_priority.state import AiWorkload
from app.infrastructure.documents.storage_transfers import finish_cleanup_despite_cancellation


async def record_provider_event(
    metrics: AiPriorityMetrics,
    *,
    workload: AiWorkload,
    event: str,
    duration_ms: float | None = None,
    retry_number: int | None = None,
) -> None:
    # Both Redis and optional registry export sinks are synchronous. Await the
    # same bounded write without blocking the loop or abandoning its thread.
    await finish_cleanup_despite_cancellation(
        asyncio.to_thread(
            metrics.record_provider_event,
            workload=workload,
            event=event,
            duration_ms=duration_ms,
            retry_number=retry_number,
        )
    )
