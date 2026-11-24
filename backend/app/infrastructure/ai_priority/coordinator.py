"""Global extraction-first admission coordinator."""

from __future__ import annotations

import hashlib
import socket
import time
from collections.abc import Callable

from app.core.logging.logger import get_logger
from app.infrastructure.ai_priority import extraction_admission as _extraction_admission
from app.infrastructure.ai_priority import verification_admission as _verification_admission
from app.infrastructure.ai_priority.config import AiPriorityConfig
from app.infrastructure.ai_priority.metrics import AiPriorityMetrics
from app.infrastructure.ai_priority.state import (
    AdmissionDecision,
    AdmissionStatus,
    AiWorkload,
    AtomicPriorityStore,
    PriorityLease,
    QueueCounts,
    StoreMutation,
)

logger = get_logger(__name__)


class AiPriorityCoordinator:
    """Coordinate Gemini work globally without process-local admission state."""

    def __init__(
        self,
        *,
        store: AtomicPriorityStore,
        config: AiPriorityConfig | None = None,
        metrics_sink: AiPriorityMetrics | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._store = store
        self.config = config or AiPriorityConfig()
        self._metrics = metrics_sink or AiPriorityMetrics()
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._metrics.record_capacity(
            extraction_max=self.config.extraction_max_concurrency,
            verification_max=self.config.verification_max_concurrency,
        )

    def queue_extraction(self, job_reference: str) -> PriorityLease:
        """Register durable extraction demand before broker publication."""

        return _extraction_admission.queue_extraction(self, job_reference)

    def reserve_public_extraction(self, job_reference: str) -> AdmissionDecision:
        """Reserve capacity for active work plus one waiting batch of uploads."""

        return _extraction_admission.reserve_public_extraction(self, job_reference)

    def mark_extraction_dispatched(self, lease: PriorityLease) -> bool:
        return _extraction_admission.mark_extraction_dispatched(self, lease)

    def release_public_reservation(self, lease: PriorityLease) -> bool:
        """Release an abandoned waiting reservation, never an adopted delivery."""

        return _extraction_admission.release_public_reservation(self, lease)

    def try_start_extraction(self, job_reference: str) -> AdmissionDecision:
        return _extraction_admission.try_start_extraction(self, job_reference)

    def queue_verification(self, job_reference: str) -> PriorityLease:
        """Record verification backlog; failure never grants verification."""

        return _verification_admission.queue_verification(self, job_reference)

    def try_start_verification(self, job_reference: str) -> AdmissionDecision:
        return _verification_admission.try_start_verification(self, job_reference)

    def heartbeat(self, lease: PriorityLease) -> bool:
        if not lease.redis_available:
            return True
        operation = f"heartbeat_{lease.workload.value}"
        try:
            result = self._mutate(
                operation=operation,
                job_key=lease.job_key,
                generation=lease.generation,
                lease_ms=lease.lease_ms,
                max_concurrency=self._max_concurrency(lease.workload),
            )
        except Exception as exc:
            # An already admitted call is never pre-empted.  Its bounded lease
            # will recover globally if this process crashes or stays isolated.
            self._record_store_failure(lease.workload, exc)
            return False
        self._metrics.record_counts(result.counts)
        return result.code == "heartbeat"

    def release(self, lease: PriorityLease) -> bool:
        if not lease.redis_available:
            self._metrics.record_completed(lease, now_ms=self._clock_ms())
            return True
        operation = f"release_{lease.workload.value}"
        try:
            result = self._mutate(
                operation=operation,
                job_key=lease.job_key,
                generation=lease.generation,
                lease_ms=lease.lease_ms,
                max_concurrency=self._max_concurrency(lease.workload),
            )
        except Exception as exc:
            self._record_store_failure(lease.workload, exc)
            return False
        self._metrics.record_counts(result.counts)
        if result.code == "released":
            self._metrics.record_completed(lease, now_ms=self._clock_ms())
        return result.code in {"released", "released_idempotent"}

    def snapshot(self) -> QueueCounts:
        result = self._mutate(
            operation="snapshot",
            job_key="snapshot",
            generation=0,
            lease_ms=1,
            max_concurrency=1,
        )
        self._metrics.record_counts(result.counts)
        return result.counts

    def _mutate(
        self,
        *,
        operation: str,
        job_key: str,
        generation: int,
        lease_ms: int,
        max_concurrency: int,
    ) -> StoreMutation:
        return self._store.mutate(
            operation=operation,
            job_key=job_key,
            generation=generation,
            now_ms=self._clock_ms(),
            lease_ms=lease_ms,
            waiting_lease_ms=self.config.waiting_lease_ms,
            max_concurrency=max_concurrency,
            quiet_period_ms=self.config.extraction_quiet_period_ms,
        )

    def _decision(
        self,
        *,
        workload: AiWorkload,
        lease: PriorityLease,
        result: StoreMutation,
    ) -> AdmissionDecision:
        if result.code in {"admitted", "reserved", "existing_reservation"}:
            status = AdmissionStatus.ADMITTED
        elif result.code == "duplicate_active":
            status = AdmissionStatus.DUPLICATE
        elif result.code == "stale":
            status = AdmissionStatus.STALE
        else:
            status = AdmissionStatus.DEFERRED
        retry_after_ms = result.retry_after_ms
        if status in {
            AdmissionStatus.DEFERRED,
            AdmissionStatus.DUPLICATE,
            AdmissionStatus.STALE,
        }:
            retry_after_ms = max(
                retry_after_ms,
                self.config.admission_retry_ms,
            )
        return AdmissionDecision(
            status=status,
            reason=result.code,
            lease=lease,
            counts=result.counts,
            retry_after_ms=retry_after_ms,
        )

    def _record_decision(
        self,
        decision: AdmissionDecision,
        started: float,
    ) -> None:
        self._metrics.record_counts(decision.counts)
        self._metrics.record_admission(
            workload=decision.lease.workload,
            status=decision.status,
            reason=decision.reason,
            duration_ms=self._elapsed_ms(started),
        )
        if decision.admitted:
            self._metrics.record_started(
                decision.lease,
                now_ms=self._clock_ms(),
            )
        logger.info(
            "ai_priority_admission_decision",
            workload=decision.lease.workload.value,
            status=decision.status.value,
            reason=decision.reason,
            job_fingerprint=decision.lease.job_key[:16],
            extraction_waiting=decision.counts.extraction_waiting,
            extraction_dispatching=decision.counts.extraction_dispatching,
            extraction_active=decision.counts.extraction_active,
            verification_waiting=decision.counts.verification_waiting,
            verification_active=decision.counts.verification_active,
            retry_after_ms=decision.retry_after_ms,
            worker_instance=socket.gethostname()[:64],
        )

    def _record_store_failure(
        self,
        workload: AiWorkload,
        exc: Exception,
    ) -> None:
        self._metrics.record_redis_failure(workload)
        logger.warning(
            "ai_priority_redis_unavailable",
            workload=workload.value,
            error_type=type(exc).__name__,
        )

    def _max_concurrency(self, workload: AiWorkload) -> int:
        if workload == AiWorkload.EXTRACTION:
            return self.config.extraction_max_concurrency
        return self.config.verification_max_concurrency

    @staticmethod
    def _job_key(workload: AiWorkload, job_reference: str) -> str:
        # The Redis member is an irreversible fingerprint.  The source job id,
        # upload-link token, phone number, and other PII never enter Redis.
        source = f"passdetection-ai-priority-v1:{workload.value}:{job_reference}"
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return (time.perf_counter() - started) * 1000.0
