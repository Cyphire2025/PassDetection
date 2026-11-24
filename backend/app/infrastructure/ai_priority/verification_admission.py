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
)


def queue_verification(self: AdmissionContext, job_reference: str) -> PriorityLease:
    """Record verification backlog; failure never grants verification."""

    workload = AiWorkload.VERIFICATION
    self._metrics.record_request(workload)
    started = time.perf_counter()
    job_key = self._job_key(workload, job_reference)
    try:
        result = self._mutate(
            operation="register_verification",
            job_key=job_key,
            generation=0,
            lease_ms=self.config.waiting_lease_ms,
            max_concurrency=self.config.verification_max_concurrency,
        )
    except Exception as exc:
        self._record_store_failure(workload, exc)
        self._metrics.record_admission(
            workload=workload,
            status=AdmissionStatus.DEFERRED,
            reason="redis_unavailable_queue",
            duration_ms=self._elapsed_ms(started),
        )
        lease = PriorityLease(
            workload=workload,
            job_key=job_key,
            generation=0,
            lease_ms=self.config.verification_active_lease_ms,
            redis_available=False,
        )
        self._metrics.record_queued(lease, now_ms=self._clock_ms())
        return lease
    self._metrics.record_counts(result.counts)
    lease = PriorityLease(
        workload=workload,
        job_key=job_key,
        generation=result.generation,
        lease_ms=self.config.waiting_lease_ms,
    )
    self._metrics.record_queued(lease, now_ms=self._clock_ms())
    return lease


def try_start_verification(self: AdmissionContext, job_reference: str) -> AdmissionDecision:
    workload = AiWorkload.VERIFICATION
    started = time.perf_counter()
    lease = self.queue_verification(job_reference)
    if not lease.redis_available:
        decision = AdmissionDecision(
            status=AdmissionStatus.DEFERRED,
            reason="redis_unavailable_fail_closed",
            lease=lease,
            counts=QueueCounts(),
            retry_after_ms=self.config.admission_retry_ms,
        )
        self._record_decision(decision, started)
        return decision
    try:
        result = self._mutate(
            operation="start_verification",
            job_key=lease.job_key,
            generation=lease.generation,
            lease_ms=self.config.verification_active_lease_ms,
            max_concurrency=self.config.verification_max_concurrency,
        )
    except Exception as exc:
        self._record_store_failure(workload, exc)
        decision = AdmissionDecision(
            status=AdmissionStatus.DEFERRED,
            reason="redis_unavailable_fail_closed",
            lease=PriorityLease(
                workload=workload,
                job_key=lease.job_key,
                generation=lease.generation,
                lease_ms=self.config.verification_active_lease_ms,
                redis_available=False,
            ),
            counts=QueueCounts(),
            retry_after_ms=self.config.admission_retry_ms,
        )
    else:
        decision = self._decision(
            workload=workload,
            lease=PriorityLease(
                workload=workload,
                job_key=lease.job_key,
                generation=result.generation,
                lease_ms=self.config.verification_active_lease_ms,
            ),
            result=result,
        )
    self._record_decision(decision, started)
    return decision
