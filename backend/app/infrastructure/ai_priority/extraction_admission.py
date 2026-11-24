"""Workload-specific admission policy; coordinator retains public methods."""

from __future__ import annotations

import time

from app.infrastructure.ai_priority.admission_context import AdmissionContext
from app.infrastructure.ai_priority.state import (
    AdmissionDecision,
    AdmissionStatus,
    AiWorkload,
    PriorityLease,
    QueueCounts,
    StoreMutation,
)


def queue_extraction(self: AdmissionContext, job_reference: str) -> PriorityLease:
    """Register durable extraction demand before broker publication."""

    workload = AiWorkload.EXTRACTION
    self._metrics.record_request(workload)
    started = time.perf_counter()
    job_key = self._job_key(workload, job_reference)
    try:
        result = self._mutate(
            operation="register_extraction",
            job_key=job_key,
            generation=0,
            lease_ms=self.config.waiting_lease_ms,
            max_concurrency=self.config.extraction_max_concurrency,
        )
    except Exception as exc:
        self._record_store_failure(workload, exc)
        self._metrics.record_admission(
            workload=workload,
            status=AdmissionStatus.FAIL_OPEN,
            reason="redis_unavailable_queue",
            duration_ms=self._elapsed_ms(started),
        )
        lease = PriorityLease(
            workload=workload,
            job_key=job_key,
            generation=0,
            lease_ms=self.config.extraction_active_lease_ms,
            redis_available=False,
        )
        self._metrics.record_queued(lease, now_ms=self._clock_ms())
        return lease
    self._metrics.record_counts(result.counts)
    self._metrics.record_admission(
        workload=workload,
        status=AdmissionStatus.ADMITTED,
        reason=result.code,
        duration_ms=self._elapsed_ms(started),
    )
    lease = PriorityLease(
        workload=workload,
        job_key=job_key,
        generation=result.generation,
        lease_ms=self.config.waiting_lease_ms,
    )
    self._metrics.record_queued(lease, now_ms=self._clock_ms())
    return lease


def reserve_public_extraction(self: AdmissionContext, job_reference: str) -> AdmissionDecision:
    """Reserve capacity for active work plus one waiting batch of uploads."""

    workload = AiWorkload.EXTRACTION
    started = time.perf_counter()
    self._metrics.record_request(workload)
    job_key = self._job_key(workload, job_reference)
    try:
        result = self._mutate(
            operation="reserve_public_extraction",
            job_key=job_key,
            generation=0,
            lease_ms=self.config.waiting_lease_ms,
            max_concurrency=self.config.extraction_max_concurrency * 2,
        )
    except Exception as exc:
        self._record_store_failure(workload, exc)
        result = StoreMutation(
            code="admission_unavailable",
            generation=0,
            counts=QueueCounts(),
        )
    decision = self._decision(
        workload=workload,
        lease=PriorityLease(
            workload=workload,
            job_key=job_key,
            generation=result.generation,
            lease_ms=self.config.waiting_lease_ms,
        ),
        result=result,
    )
    # Reservation is queued demand, not a started provider call.
    self._metrics.record_counts(result.counts)
    self._metrics.record_admission(
        workload=workload,
        status=decision.status,
        reason=decision.reason,
        duration_ms=self._elapsed_ms(started),
    )
    if decision.admitted:
        self._metrics.record_queued(decision.lease, now_ms=self._clock_ms())
    return decision


def mark_extraction_dispatched(self: AdmissionContext, lease: PriorityLease) -> bool:
    if not lease.redis_available:
        return True
    try:
        result = self._mutate(
            operation="dispatch_extraction",
            job_key=lease.job_key,
            generation=lease.generation,
            lease_ms=self.config.dispatching_lease_ms,
            max_concurrency=self.config.extraction_max_concurrency,
        )
    except Exception as exc:
        # Extraction remains available on a scheduler outage.  The worker
        # will retry registration and, if Redis is still down, fail open.
        self._record_store_failure(AiWorkload.EXTRACTION, exc)
        return True
    self._metrics.record_counts(result.counts)
    return result.code not in {"stale", "missing", "invalid_operation"}


def release_public_reservation(self: AdmissionContext, lease: PriorityLease) -> bool:
    """Release an abandoned waiting reservation, never an adopted delivery."""

    try:
        result = self._mutate(
            operation="release_public_extraction",
            job_key=lease.job_key,
            generation=lease.generation,
            lease_ms=lease.lease_ms,
            max_concurrency=self.config.extraction_max_concurrency,
        )
    except Exception as exc:
        self._record_store_failure(AiWorkload.EXTRACTION, exc)
        return False
    self._metrics.record_counts(result.counts)
    return result.code in {"released", "released_idempotent", "reservation_in_use"}


def try_start_extraction(self: AdmissionContext, job_reference: str) -> AdmissionDecision:
    workload = AiWorkload.EXTRACTION
    started = time.perf_counter()
    lease = self.queue_extraction(job_reference)
    if not lease.redis_available:
        self._metrics.record_started(lease, now_ms=self._clock_ms())
        return AdmissionDecision(
            status=AdmissionStatus.FAIL_OPEN,
            reason="redis_unavailable_fail_open",
            lease=lease,
            counts=QueueCounts(),
        )
    try:
        result = self._mutate(
            operation="start_extraction",
            job_key=lease.job_key,
            generation=lease.generation,
            lease_ms=self.config.extraction_active_lease_ms,
            max_concurrency=self.config.extraction_max_concurrency,
        )
    except Exception as exc:
        self._record_store_failure(workload, exc)
        fail_open_lease = PriorityLease(
            workload=workload,
            job_key=lease.job_key,
            generation=lease.generation,
            lease_ms=self.config.extraction_active_lease_ms,
            redis_available=False,
        )
        decision = AdmissionDecision(
            status=AdmissionStatus.FAIL_OPEN,
            reason="redis_unavailable_fail_open",
            lease=fail_open_lease,
            counts=QueueCounts(),
        )
    else:
        decision = self._decision(
            workload=workload,
            lease=PriorityLease(
                workload=workload,
                job_key=lease.job_key,
                generation=result.generation,
                lease_ms=self.config.extraction_active_lease_ms,
            ),
            result=result,
        )
    self._record_decision(decision, started)
    return decision
