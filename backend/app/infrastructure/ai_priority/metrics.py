"""AI metric bridge and stable imports for focused metric store owners."""

from __future__ import annotations

from functools import lru_cache

from app.core.config.settings import get_settings
from app.infrastructure.ai_priority.metrics_contract import (
    SharedAiMetricsStore as SharedAiMetricsStore,
)
from app.infrastructure.ai_priority.metrics_memory import (
    InMemoryAiMetricsStore as InMemoryAiMetricsStore,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _ADMISSION_REASONS as _ADMISSION_REASONS,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _DEFAULT_CIRCUIT_SECONDS as _DEFAULT_CIRCUIT_SECONDS,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _DEFAULT_LIFECYCLE_SECONDS as _DEFAULT_LIFECYCLE_SECONDS,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _DEFAULT_MAX_SAMPLES as _DEFAULT_MAX_SAMPLES,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _DEFAULT_RETENTION_SECONDS as _DEFAULT_RETENTION_SECONDS,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _HISTOGRAM_NAMES as _HISTOGRAM_NAMES,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _MAX_LOCAL_LIFECYCLES as _MAX_LOCAL_LIFECYCLES,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _PROVIDER_EVENTS as _PROVIDER_EVENTS,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _bounded_category as _bounded_category,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _bounded_number as _bounded_number,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _histogram_snapshot as _histogram_snapshot,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _lifecycle_identity as _lifecycle_identity,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _metrics_snapshot as _metrics_snapshot,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _optional_float as _optional_float,
)
from app.infrastructure.ai_priority.metrics_policy import (
    _percentile as _percentile,
)
from app.infrastructure.ai_priority.metrics_redis import (
    RedisAiMetricsStore as RedisAiMetricsStore,
)
from app.infrastructure.ai_priority.metrics_resilient import (
    ResilientAiMetricsStore as ResilientAiMetricsStore,
)
from app.infrastructure.ai_priority.metrics_scripts import (
    _COMPLETE_LIFECYCLE_SCRIPT as _COMPLETE_LIFECYCLE_SCRIPT,
)
from app.infrastructure.ai_priority.metrics_scripts import (
    _OBSERVE_SCRIPT as _OBSERVE_SCRIPT,
)
from app.infrastructure.ai_priority.metrics_scripts import (
    _QUEUE_LIFECYCLE_SCRIPT as _QUEUE_LIFECYCLE_SCRIPT,
)
from app.infrastructure.ai_priority.metrics_scripts import (
    _START_LIFECYCLE_SCRIPT as _START_LIFECYCLE_SCRIPT,
)
from app.infrastructure.ai_priority.state import (
    AdmissionStatus,
    AiWorkload,
    PriorityLease,
    QueueCounts,
)
from app.infrastructure.observability.metrics import MetricsRegistry, metrics


@lru_cache(maxsize=1)
def get_shared_ai_priority_metrics_store() -> ResilientAiMetricsStore:
    """Build one process-local adapter to the shared Redis aggregates."""

    try:
        redis_url = get_settings().redis.broker_url
        remote: SharedAiMetricsStore | None = RedisAiMetricsStore.from_url(redis_url)
    except Exception:
        remote = None
    return ResilientAiMetricsStore(remote)


class AiPriorityMetrics:
    def __init__(
        self,
        registry: MetricsRegistry = metrics,
        shared_store: SharedAiMetricsStore | None = None,
    ) -> None:
        self._registry = registry
        self._shared = (
            shared_store if shared_store is not None else get_shared_ai_priority_metrics_store()
        )

    def record_request(self, workload: AiWorkload) -> None:
        name = f"ai_priority.requests.total.{workload.value}"
        self._registry.increment(name)
        self._shared.increment(name)

    def record_admission(
        self,
        *,
        workload: AiWorkload,
        status: AdmissionStatus,
        reason: str,
        duration_ms: float,
    ) -> None:
        admission_name = f"ai_priority.admissions.total.{workload.value}.{status.value}"
        normalized_reason = _bounded_category(reason, _ADMISSION_REASONS)
        reason_name = f"ai_priority.admissions.reason.{workload.value}.{normalized_reason}"
        duration_name = f"ai_priority.admission_latency_ms.{workload.value}"
        self._registry.increment(admission_name)
        self._registry.increment(reason_name)
        self._registry.observe(duration_name, duration_ms)
        self._shared.increment(admission_name)
        self._shared.increment(reason_name)
        self._shared.observe(duration_name, duration_ms)

    def record_redis_failure(self, workload: AiWorkload) -> None:
        name = f"ai_priority.redis_failures.total.{workload.value}"
        self._registry.increment(name)
        self._shared.increment(name)

    def record_capacity(
        self,
        *,
        extraction_max: int,
        verification_max: int,
    ) -> None:
        values = {
            "ai_priority.capacity.extraction_max": extraction_max,
            "ai_priority.capacity.verification_max": verification_max,
        }
        for name, value in values.items():
            self._registry.set_gauge(name, value)
        self._shared.set_gauges(values)

    def record_counts(self, counts: QueueCounts) -> None:
        values = {
            "ai_priority.queue.extraction_waiting": counts.extraction_waiting,
            "ai_priority.queue.extraction_dispatching": (counts.extraction_dispatching),
            "ai_priority.active.extraction": counts.extraction_active,
            "ai_priority.queue.verification_waiting": (counts.verification_waiting),
            "ai_priority.active.verification": counts.verification_active,
        }
        for name, value in values.items():
            self._registry.set_gauge(name, value)
        self._shared.set_gauges(values)

    def record_queued(
        self,
        lease: PriorityLease,
        *,
        now_ms: int,
    ) -> None:
        self._shared.mark_queued(
            workload=lease.workload,
            job_key=lease.job_key,
            generation=lease.generation,
            now_ms=now_ms,
        )

    def record_started(
        self,
        lease: PriorityLease,
        *,
        now_ms: int,
    ) -> None:
        duration = self._shared.mark_started(
            workload=lease.workload,
            job_key=lease.job_key,
            generation=lease.generation,
            now_ms=now_ms,
        )
        if duration is not None:
            self._registry.observe(
                f"ai_priority.queue_wait_ms.{lease.workload.value}",
                duration,
            )

    def record_completed(
        self,
        lease: PriorityLease,
        *,
        now_ms: int,
    ) -> None:
        duration = self._shared.mark_completed(
            workload=lease.workload,
            job_key=lease.job_key,
            generation=lease.generation,
            now_ms=now_ms,
        )
        if duration is not None:
            self._registry.observe(
                f"ai_priority.end_to_end_latency_ms.{lease.workload.value}",
                duration,
            )

    def record_provider_event(
        self,
        *,
        workload: AiWorkload,
        event: str,
        duration_ms: float | None = None,
        retry_number: int | None = None,
    ) -> None:
        """Record only fixed provider categories and bounded numeric values."""

        normalized_event = _bounded_category(event, _PROVIDER_EVENTS)
        event_name = f"ai_provider.events.total.{workload.value}.{normalized_event}"
        self._registry.increment(event_name)
        self._shared.increment(event_name)
        if duration_ms is not None:
            duration_name = f"ai_provider.duration_ms.{workload.value}"
            self._registry.observe(duration_name, duration_ms)
            self._shared.observe(duration_name, duration_ms)
        if retry_number is not None and normalized_event == "retry":
            retry_name = f"ai_provider.retry_number.{workload.value}"
            bounded_retry = float(max(0, min(retry_number, 100)))
            self._registry.observe(retry_name, bounded_retry)
            self._shared.observe(retry_name, bounded_retry)


metrics.register_snapshot_provider(
    "ai_priority",
    lambda: get_shared_ai_priority_metrics_store().snapshot(),
)
