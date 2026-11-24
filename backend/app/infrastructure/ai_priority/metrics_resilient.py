"""Local mirror and short-circuit policy for shared AI metrics."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from threading import RLock
from typing import Any

from app.infrastructure.ai_priority.metrics_contract import SharedAiMetricsStore
from app.infrastructure.ai_priority.metrics_memory import InMemoryAiMetricsStore
from app.infrastructure.ai_priority.metrics_policy import _DEFAULT_CIRCUIT_SECONDS
from app.infrastructure.ai_priority.state import AiWorkload


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


ResilientAiMetricsStore.__module__ = "app.infrastructure.ai_priority.metrics"
