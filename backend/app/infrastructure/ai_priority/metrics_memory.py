"""Thread-safe bounded process fallback for AI metrics."""

from __future__ import annotations

from collections import OrderedDict, defaultdict, deque
from collections.abc import Mapping
from threading import RLock
from typing import Any

from app.infrastructure.ai_priority.metrics_policy import (
    _DEFAULT_MAX_SAMPLES,
    _MAX_LOCAL_LIFECYCLES,
    _bounded_number,
    _lifecycle_identity,
    _metrics_snapshot,
)
from app.infrastructure.ai_priority.state import AiWorkload


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
                samples={name: list(values) for name, values in self._samples.items()},
                histogram_totals=dict(self._histogram_totals),
                max_samples=self.max_samples,
            )

    def _observe_locked(self, name: str, value: float) -> None:
        self._samples[name].append(value)
        self._histogram_totals[name] += 1


InMemoryAiMetricsStore.__module__ = "app.infrastructure.ai_priority.metrics"
