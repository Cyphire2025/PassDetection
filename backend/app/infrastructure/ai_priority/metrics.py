"""Shared, bounded metrics for Gemini admission and provider runtimes."""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections import OrderedDict, defaultdict, deque
from collections.abc import Callable, Mapping
from functools import lru_cache
from threading import RLock
from typing import Any, Final, Protocol

from redis import Redis

from app.core.config.settings import get_settings
from app.infrastructure.ai_priority.state import (
    AdmissionStatus,
    AiWorkload,
    PriorityLease,
    QueueCounts,
)
from app.infrastructure.observability.metrics import MetricsRegistry, metrics

_DEFAULT_MAX_SAMPLES: Final[int] = 2_048
_DEFAULT_RETENTION_SECONDS: Final[int] = 7 * 24 * 60 * 60
_DEFAULT_LIFECYCLE_SECONDS: Final[int] = 6 * 60 * 60
_DEFAULT_CIRCUIT_SECONDS: Final[float] = 30.0
_MAX_LOCAL_LIFECYCLES: Final[int] = 4_096

_ADMISSION_REASONS: Final[frozenset[str]] = frozenset(
    {
        "admitted",
        "already_active",
        "already_dispatching",
        "deferred_capacity",
        "deferred_extraction_priority",
        "deferred_quiet_period",
        "duplicate_active",
        "existing_active",
        "existing_dispatching",
        "existing_waiting",
        "missing",
        "redis_unavailable_fail_closed",
        "redis_unavailable_fail_open",
        "redis_unavailable_queue",
        "registered",
        "released",
        "released_idempotent",
        "stale",
    }
)
_PROVIDER_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "network_error",
        "provider_request_error",
        "retry",
        "success",
        "timeout",
        "upstream_429",
        "upstream_failure",
    }
)
_HISTOGRAM_NAMES: Final[tuple[str, ...]] = tuple(
    metric
    for workload in AiWorkload
    for metric in (
        f"ai_priority.admission_latency_ms.{workload.value}",
        f"ai_priority.queue_wait_ms.{workload.value}",
        f"ai_priority.end_to_end_latency_ms.{workload.value}",
        f"ai_provider.duration_ms.{workload.value}",
        f"ai_provider.retry_number.{workload.value}",
    )
)

_QUEUE_LIFECYCLE_SCRIPT: Final[str] = r"""
local lifecycle_key = KEYS[1]
local queued_ms = tonumber(ARGV[1])
local lifecycle_seconds = tonumber(ARGV[2])

redis.call("HSETNX", lifecycle_key, "queued_ms", queued_ms)
redis.call("EXPIRE", lifecycle_key, lifecycle_seconds)
return true
"""

_OBSERVE_SCRIPT: Final[str] = r"""
local samples_key = KEYS[1]
local totals_key = KEYS[2]
local metric_name = ARGV[1]
local value = ARGV[2]
local max_samples = tonumber(ARGV[3])
local retention_seconds = tonumber(ARGV[4])

redis.call("HINCRBY", totals_key, metric_name, 1)
redis.call("EXPIRE", totals_key, retention_seconds)
redis.call("LPUSH", samples_key, value)
redis.call("LTRIM", samples_key, 0, max_samples - 1)
redis.call("EXPIRE", samples_key, retention_seconds)
return true
"""

_START_LIFECYCLE_SCRIPT: Final[str] = r"""
local lifecycle_key = KEYS[1]
local samples_key = KEYS[2]
local totals_key = KEYS[3]
local now_ms = tonumber(ARGV[1])
local lifecycle_seconds = tonumber(ARGV[2])
local retention_seconds = tonumber(ARGV[3])
local max_samples = tonumber(ARGV[4])
local metric_name = ARGV[5]

if redis.call("EXISTS", lifecycle_key) == 0 then
  return false
end
if redis.call("HSETNX", lifecycle_key, "started_ms", now_ms) == 0 then
  return false
end
redis.call("EXPIRE", lifecycle_key, lifecycle_seconds)
local queued_ms = tonumber(redis.call("HGET", lifecycle_key, "queued_ms"))
if not queued_ms then
  return false
end
local duration_ms = math.max(0, now_ms - queued_ms)
redis.call("HINCRBY", totals_key, metric_name, 1)
redis.call("EXPIRE", totals_key, retention_seconds)
redis.call("LPUSH", samples_key, tostring(duration_ms))
redis.call("LTRIM", samples_key, 0, max_samples - 1)
redis.call("EXPIRE", samples_key, retention_seconds)
return tostring(duration_ms)
"""

_COMPLETE_LIFECYCLE_SCRIPT: Final[str] = r"""
local lifecycle_key = KEYS[1]
local samples_key = KEYS[2]
local totals_key = KEYS[3]
local now_ms = tonumber(ARGV[1])
local retention_seconds = tonumber(ARGV[2])
local max_samples = tonumber(ARGV[3])
local metric_name = ARGV[4]

local queued_ms = tonumber(redis.call("HGET", lifecycle_key, "queued_ms"))
if not queued_ms then
  return false
end
if redis.call("HSETNX", lifecycle_key, "completed_ms", now_ms) == 0 then
  return false
end
local duration_ms = math.max(0, now_ms - queued_ms)
redis.call("HINCRBY", totals_key, metric_name, 1)
redis.call("EXPIRE", totals_key, retention_seconds)
redis.call("LPUSH", samples_key, tostring(duration_ms))
redis.call("LTRIM", samples_key, 0, max_samples - 1)
redis.call("EXPIRE", samples_key, retention_seconds)
redis.call("DEL", lifecycle_key)
return tostring(duration_ms)
"""


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


class InMemoryAiMetricsStore:
    """Thread-safe, bounded process fallback for shared metrics."""

    def __init__(
        self,
        *,
        max_samples: int = _DEFAULT_MAX_SAMPLES,
        max_lifecycles: int = _MAX_LOCAL_LIFECYCLES,
    ) -> None:
        self.max_samples = max(1, max_samples)
        self._max_lifecycles = max(1, max_lifecycles)
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}
        self._samples: defaultdict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.max_samples)
        )
        self._histogram_totals: defaultdict[str, int] = defaultdict(int)
        self._lifecycles: OrderedDict[str, dict[str, int]] = OrderedDict()
        self._lock = RLock()

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def observe(self, name: str, value: float) -> None:
        bounded = _bounded_number(value)
        if bounded is None:
            return
        with self._lock:
            self._samples[name].append(bounded)
            self._histogram_totals[name] += 1

    def set_gauge(self, name: str, value: float) -> None:
        bounded = _bounded_number(value)
        if bounded is None:
            return
        with self._lock:
            self._gauges[name] = bounded

    def set_gauges(self, values: Mapping[str, float]) -> None:
        with self._lock:
            for name, value in values.items():
                bounded = _bounded_number(value)
                if bounded is not None:
                    self._gauges[name] = bounded

    def mark_queued(
        self,
        *,
        workload: AiWorkload,
        job_key: str,
        generation: int,
        now_ms: int,
    ) -> None:
        lifecycle = _lifecycle_identity(workload, job_key, generation)
        with self._lock:
            state = self._lifecycles.setdefault(lifecycle, {})
            state.setdefault("queued_ms", now_ms)
            self._lifecycles.move_to_end(lifecycle)
            while len(self._lifecycles) > self._max_lifecycles:
                self._lifecycles.popitem(last=False)

    def mark_started(
        self,
        *,
        workload: AiWorkload,
        job_key: str,
        generation: int,
        now_ms: int,
    ) -> float | None:
        lifecycle = _lifecycle_identity(workload, job_key, generation)
        with self._lock:
            state = self._lifecycles.get(lifecycle)
            if state is None or "started_ms" in state:
                return None
            queued_ms = state.get("queued_ms")
            if queued_ms is None:
                return None
            state["started_ms"] = now_ms
            duration_ms = float(max(0, now_ms - queued_ms))
            self._observe_locked(
                f"ai_priority.queue_wait_ms.{workload.value}",
                duration_ms,
            )
            return duration_ms

    def mark_completed(
        self,
        *,
        workload: AiWorkload,
        job_key: str,
        generation: int,
        now_ms: int,
    ) -> float | None:
        lifecycle = _lifecycle_identity(workload, job_key, generation)
        with self._lock:
            state = self._lifecycles.pop(lifecycle, None)
            if state is None:
                return None
            queued_ms = state.get("queued_ms")
            if queued_ms is None:
                return None
            duration_ms = float(max(0, now_ms - queued_ms))
            self._observe_locked(
                f"ai_priority.end_to_end_latency_ms.{workload.value}",
                duration_ms,
            )
            return duration_ms

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return _metrics_snapshot(
                counters=dict(self._counters),
                gauges=dict(self._gauges),
                samples={
                    name: list(values)
                    for name, values in self._samples.items()
                },
                histogram_totals=dict(self._histogram_totals),
                max_samples=self.max_samples,
            )

    def _observe_locked(self, name: str, value: float) -> None:
        self._samples[name].append(value)
        self._histogram_totals[name] += 1


class RedisAiMetricsStore:
    """Atomic Redis aggregates and latest-N latency samples."""

    def __init__(
        self,
        redis_client: Any,
        *,
        namespace: str = "passdetection:{ai-observability}:v1",
        max_samples: int = _DEFAULT_MAX_SAMPLES,
        retention_seconds: int = _DEFAULT_RETENTION_SECONDS,
        lifecycle_seconds: int = _DEFAULT_LIFECYCLE_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._namespace = namespace
        self.max_samples = max(1, max_samples)
        self._retention_seconds = max(60, retention_seconds)
        self._lifecycle_seconds = max(60, lifecycle_seconds)
        self._counters_key = f"{namespace}:counters"
        self._gauges_key = f"{namespace}:gauges"
        self._histogram_totals_key = f"{namespace}:histogram-totals"

    @classmethod
    def from_url(cls, redis_url: str) -> RedisAiMetricsStore:
        return cls(
            Redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=0.15,
                socket_timeout=0.25,
                health_check_interval=30,
            )
        )

    def increment(self, name: str, amount: int = 1) -> None:
        pipeline = self._redis.pipeline(transaction=False)
        pipeline.hincrby(self._counters_key, name, amount)
        pipeline.expire(self._counters_key, self._retention_seconds)
        pipeline.execute()

    def observe(self, name: str, value: float) -> None:
        bounded = _bounded_number(value)
        if bounded is None:
            return
        samples_key = self._histogram_key(name)
        self._redis.eval(
            _OBSERVE_SCRIPT,
            2,
            samples_key,
            self._histogram_totals_key,
            name,
            repr(bounded),
            self.max_samples,
            self._retention_seconds,
        )

    def set_gauge(self, name: str, value: float) -> None:
        bounded = _bounded_number(value)
        if bounded is None:
            return
        pipeline = self._redis.pipeline(transaction=False)
        pipeline.hset(self._gauges_key, name, repr(bounded))
        pipeline.expire(self._gauges_key, self._retention_seconds)
        pipeline.execute()

    def set_gauges(self, values: Mapping[str, float]) -> None:
        bounded = {
            name: repr(numeric)
            for name, value in values.items()
            if (numeric := _bounded_number(value)) is not None
        }
        if not bounded:
            return
        pipeline = self._redis.pipeline(transaction=False)
        pipeline.hset(self._gauges_key, mapping=bounded)
        pipeline.expire(self._gauges_key, self._retention_seconds)
        pipeline.execute()

    def mark_queued(
        self,
        *,
        workload: AiWorkload,
        job_key: str,
        generation: int,
        now_ms: int,
    ) -> None:
        lifecycle_key = self._lifecycle_key(workload, job_key, generation)
        self._redis.eval(
            _QUEUE_LIFECYCLE_SCRIPT,
            1,
            lifecycle_key,
            now_ms,
            self._lifecycle_seconds,
        )

    def mark_started(
        self,
        *,
        workload: AiWorkload,
        job_key: str,
        generation: int,
        now_ms: int,
    ) -> float | None:
        metric = f"ai_priority.queue_wait_ms.{workload.value}"
        raw = self._redis.eval(
            _START_LIFECYCLE_SCRIPT,
            3,
            self._lifecycle_key(workload, job_key, generation),
            self._histogram_key(metric),
            self._histogram_totals_key,
            now_ms,
            self._lifecycle_seconds,
            self._retention_seconds,
            self.max_samples,
            metric,
        )
        return _optional_float(raw)

    def mark_completed(
        self,
        *,
        workload: AiWorkload,
        job_key: str,
        generation: int,
        now_ms: int,
    ) -> float | None:
        metric = f"ai_priority.end_to_end_latency_ms.{workload.value}"
        raw = self._redis.eval(
            _COMPLETE_LIFECYCLE_SCRIPT,
            3,
            self._lifecycle_key(workload, job_key, generation),
            self._histogram_key(metric),
            self._histogram_totals_key,
            now_ms,
            self._retention_seconds,
            self.max_samples,
            metric,
        )
        return _optional_float(raw)

    def snapshot(self) -> dict[str, Any]:
        pipeline = self._redis.pipeline(transaction=False)
        pipeline.hgetall(self._counters_key)
        pipeline.hgetall(self._gauges_key)
        pipeline.hgetall(self._histogram_totals_key)
        for name in _HISTOGRAM_NAMES:
            pipeline.lrange(self._histogram_key(name), 0, self.max_samples - 1)
        raw = pipeline.execute()
        counters = {
            str(name): int(value)
            for name, value in dict(raw[0] or {}).items()
        }
        gauges = {
            str(name): float(value)
            for name, value in dict(raw[1] or {}).items()
        }
        histogram_totals = {
            str(name): int(value)
            for name, value in dict(raw[2] or {}).items()
        }
        samples = {
            name: [
                parsed
                for value in (raw[index + 3] or [])
                if (parsed := _optional_float(value)) is not None
            ]
            for index, name in enumerate(_HISTOGRAM_NAMES)
        }
        return _metrics_snapshot(
            counters=counters,
            gauges=gauges,
            samples=samples,
            histogram_totals=histogram_totals,
            max_samples=self.max_samples,
        )

    def _histogram_key(self, metric_name: str) -> str:
        return f"{self._namespace}:histogram:{metric_name}"

    def _lifecycle_key(
        self,
        workload: AiWorkload,
        job_key: str,
        generation: int,
    ) -> str:
        lifecycle = _lifecycle_identity(workload, job_key, generation)
        return f"{self._namespace}:lifecycle:{lifecycle}"


class ResilientAiMetricsStore:
    """Mirror locally and use Redis whenever its short circuit is closed."""

    def __init__(
        self,
        remote: SharedAiMetricsStore | None,
        *,
        local: InMemoryAiMetricsStore | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        circuit_seconds: float = _DEFAULT_CIRCUIT_SECONDS,
    ) -> None:
        self._remote = remote
        self._local = local or InMemoryAiMetricsStore()
        self._monotonic = monotonic
        self._circuit_seconds = max(0.1, circuit_seconds)
        self._circuit_open_until = 0.0
        self._lock = RLock()

    def increment(self, name: str, amount: int = 1) -> None:
        self._local.increment(name, amount)
        self._write_remote(lambda store: store.increment(name, amount))

    def observe(self, name: str, value: float) -> None:
        self._local.observe(name, value)
        self._write_remote(lambda store: store.observe(name, value))

    def set_gauge(self, name: str, value: float) -> None:
        self._local.set_gauge(name, value)
        self._write_remote(lambda store: store.set_gauge(name, value))

    def set_gauges(self, values: Mapping[str, float]) -> None:
        self._local.set_gauges(values)
        self._write_remote(lambda store: store.set_gauges(values))

    def mark_queued(
        self,
        *,
        workload: AiWorkload,
        job_key: str,
        generation: int,
        now_ms: int,
    ) -> None:
        self._local.mark_queued(
            workload=workload,
            job_key=job_key,
            generation=generation,
            now_ms=now_ms,
        )
        self._write_remote(
            lambda store: store.mark_queued(
                workload=workload,
                job_key=job_key,
                generation=generation,
                now_ms=now_ms,
            )
        )

    def mark_started(
        self,
        *,
        workload: AiWorkload,
        job_key: str,
        generation: int,
        now_ms: int,
    ) -> float | None:
        duration = self._local.mark_started(
            workload=workload,
            job_key=job_key,
            generation=generation,
            now_ms=now_ms,
        )
        self._write_remote(
            lambda store: store.mark_started(
                workload=workload,
                job_key=job_key,
                generation=generation,
                now_ms=now_ms,
            )
        )
        return duration

    def mark_completed(
        self,
        *,
        workload: AiWorkload,
        job_key: str,
        generation: int,
        now_ms: int,
    ) -> float | None:
        duration = self._local.mark_completed(
            workload=workload,
            job_key=job_key,
            generation=generation,
            now_ms=now_ms,
        )
        self._write_remote(
            lambda store: store.mark_completed(
                workload=workload,
                job_key=job_key,
                generation=generation,
                now_ms=now_ms,
            )
        )
        return duration

    def snapshot(self) -> dict[str, Any]:
        remote = self._remote
        if remote is not None and not self._circuit_is_open():
            try:
                snapshot = remote.snapshot()
            except Exception:
                self._open_circuit()
            else:
                self._close_circuit()
                return {
                    "status": "ok",
                    "source": "redis",
                    "scope": "all_api_and_worker_processes",
                    **snapshot,
                }
        return {
            "status": "degraded",
            "source": "process_fallback",
            "scope": "current_process_only",
            "limitation": "redis_unavailable_samples_are_not_backfilled",
            **self._local.snapshot(),
        }

    def _write_remote(
        self,
        operation: Callable[[SharedAiMetricsStore], object],
    ) -> None:
        remote = self._remote
        if remote is None or self._circuit_is_open():
            return
        try:
            operation(remote)
        except Exception:
            self._open_circuit()
        else:
            self._close_circuit()

    def _circuit_is_open(self) -> bool:
        with self._lock:
            return self._monotonic() < self._circuit_open_until

    def _open_circuit(self) -> None:
        with self._lock:
            self._circuit_open_until = self._monotonic() + self._circuit_seconds

    def _close_circuit(self) -> None:
        with self._lock:
            self._circuit_open_until = 0.0


@lru_cache(maxsize=1)
def get_shared_ai_priority_metrics_store() -> ResilientAiMetricsStore:
    """Build one process-local adapter to the shared Redis aggregates."""

    try:
        redis_url = get_settings().redis.url
        remote: SharedAiMetricsStore | None = RedisAiMetricsStore.from_url(
            redis_url
        )
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
            shared_store
            if shared_store is not None
            else get_shared_ai_priority_metrics_store()
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
        admission_name = (
            f"ai_priority.admissions.total.{workload.value}.{status.value}"
        )
        normalized_reason = _bounded_category(reason, _ADMISSION_REASONS)
        reason_name = (
            f"ai_priority.admissions.reason.{workload.value}."
            f"{normalized_reason}"
        )
        duration_name = (
            f"ai_priority.admission_latency_ms.{workload.value}"
        )
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
            "ai_priority.queue.extraction_dispatching": (
                counts.extraction_dispatching
            ),
            "ai_priority.active.extraction": counts.extraction_active,
            "ai_priority.queue.verification_waiting": (
                counts.verification_waiting
            ),
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
        event_name = (
            f"ai_provider.events.total.{workload.value}.{normalized_event}"
        )
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


def _bounded_category(value: str, allowed: frozenset[str]) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(".", "_")
    return normalized if normalized in allowed else "other"


def _bounded_number(value: float) -> float | None:
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return max(0.0, min(numeric, 24 * 60 * 60 * 1_000.0))


def _lifecycle_identity(
    workload: AiWorkload,
    job_key: str,
    generation: int,
) -> str:
    normalized_job_key = job_key.lower()
    if re.fullmatch(r"[0-9a-f]{64}", normalized_job_key) is None:
        normalized_job_key = hashlib.sha256(job_key.encode("utf-8")).hexdigest()
    return f"{workload.value}:{normalized_job_key}:{max(0, generation)}"


def _optional_float(value: object) -> float | None:
    if value is None or value is False or value == b"" or value == "":
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="strict")
    if not isinstance(value, (str, int, float)):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _metrics_snapshot(
    *,
    counters: dict[str, int],
    gauges: dict[str, float],
    samples: dict[str, list[float]],
    histogram_totals: dict[str, int],
    max_samples: int,
) -> dict[str, Any]:
    histogram_names = sorted(set(samples) | set(histogram_totals))
    return {
        "window": {
            "kind": "latest_n",
            "max_samples_per_histogram": max_samples,
        },
        "counters": dict(sorted(counters.items())),
        "gauges": dict(sorted(gauges.items())),
        "histograms": {
            name: _histogram_snapshot(
                samples.get(name, []),
                total=histogram_totals.get(name, 0),
            )
            for name in histogram_names
        },
    }


def _histogram_snapshot(
    values: list[float],
    *,
    total: int,
) -> dict[str, float | int | None]:
    ordered = sorted(values)
    if not ordered:
        return {
            "count_total": total,
            "count_window": 0,
            "avg": 0.0,
            "min": None,
            "max": None,
            "p50": None,
            "p95": None,
            "p99": None,
        }
    return {
        "count_total": max(total, len(ordered)),
        "count_window": len(ordered),
        "avg": round(sum(ordered) / len(ordered), 4),
        "min": ordered[0],
        "max": ordered[-1],
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "p99": _percentile(ordered, 0.99),
    }


def _percentile(ordered: list[float], percentile: float) -> float:
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[min(len(ordered) - 1, rank - 1)]


metrics.register_snapshot_provider(
    "ai_priority",
    lambda: get_shared_ai_priority_metrics_store().snapshot(),
)
