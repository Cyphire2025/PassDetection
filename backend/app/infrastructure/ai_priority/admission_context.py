"""Typed call-time dependencies for workload-specific admission policy."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.infrastructure.ai_priority.config import AiPriorityConfig
from app.infrastructure.ai_priority.metrics import AiPriorityMetrics
from app.infrastructure.ai_priority.state import (
    AdmissionDecision,
    AiWorkload,
    PriorityLease,
    StoreMutation,
)


class AdmissionContext(Protocol):
    config: AiPriorityConfig
    _metrics: AiPriorityMetrics
    _clock_ms: Callable[[], int]

    def queue_extraction(self, job_reference: str) -> PriorityLease: ...
    def queue_verification(self, job_reference: str) -> PriorityLease: ...
    def _mutate(
        self, *, operation: str, job_key: str, generation: int, lease_ms: int, max_concurrency: int
    ) -> StoreMutation: ...
    def _decision(
        self, *, workload: AiWorkload, lease: PriorityLease, result: StoreMutation
    ) -> AdmissionDecision: ...
    def _record_decision(self, decision: AdmissionDecision, started: float) -> None: ...
    def _record_store_failure(self, workload: AiWorkload, exc: Exception) -> None: ...
    def _job_key(self, workload: AiWorkload, job_reference: str) -> str: ...
    def _elapsed_ms(self, started: float) -> float: ...
