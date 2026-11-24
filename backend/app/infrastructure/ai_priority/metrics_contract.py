"""Shared metric store protocol."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from app.infrastructure.ai_priority.state import AiWorkload


class SharedAiMetricsStore(Protocol):
    """Low-cardinality aggregate store used by every API/worker process."""

    def increment(self, name: str, amount: int = 1) -> None: ...

    def observe(self, name: str, value: float) -> None: ...

    def set_gauge(self, name: str, value: float) -> None: ...

    def set_gauges(self, values: Mapping[str, float]) -> None: ...

    def mark_queued(
        self,
        *,
        workload: AiWorkload,
        job_key: str,
        generation: int,
        now_ms: int,
    ) -> None: ...

    def mark_started(
        self,
        *,
        workload: AiWorkload,
        job_key: str,
        generation: int,
        now_ms: int,
    ) -> float | None: ...

    def mark_completed(
        self,
        *,
        workload: AiWorkload,
        job_key: str,
        generation: int,
        now_ms: int,
    ) -> float | None: ...

    def snapshot(self) -> dict[str, Any]: ...


SharedAiMetricsStore.__module__ = "app.infrastructure.ai_priority.metrics"
