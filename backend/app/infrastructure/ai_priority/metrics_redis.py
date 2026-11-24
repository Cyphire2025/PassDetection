"""Atomic shared AI metrics and bounded Redis sample windows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from redis import Redis

from app.infrastructure.ai_priority.metrics_policy import (
    _DEFAULT_LIFECYCLE_SECONDS,
    _DEFAULT_MAX_SAMPLES,
    _DEFAULT_RETENTION_SECONDS,
    _HISTOGRAM_NAMES,
    _bounded_number,
    _lifecycle_identity,
    _metrics_snapshot,
    _optional_float,
)
from app.infrastructure.ai_priority.metrics_scripts import (
    _COMPLETE_LIFECYCLE_SCRIPT,
    _OBSERVE_SCRIPT,
    _QUEUE_LIFECYCLE_SCRIPT,
    _START_LIFECYCLE_SCRIPT,
)
from app.infrastructure.ai_priority.state import AiWorkload


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
        counters = {str(name): int(value) for name, value in dict(raw[0] or {}).items()}
        gauges = {str(name): float(value) for name, value in dict(raw[1] or {}).items()}
        histogram_totals = {str(name): int(value) for name, value in dict(raw[2] or {}).items()}
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


RedisAiMetricsStore.__module__ = "app.infrastructure.ai_priority.metrics"
