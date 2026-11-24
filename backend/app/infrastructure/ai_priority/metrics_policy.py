"""Bounded metric labels, numeric projections and snapshot policy."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Final

from app.infrastructure.ai_priority.state import AiWorkload

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


_bounded_category.__module__ = "app.infrastructure.ai_priority.metrics"


_bounded_number.__module__ = "app.infrastructure.ai_priority.metrics"


_lifecycle_identity.__module__ = "app.infrastructure.ai_priority.metrics"


_optional_float.__module__ = "app.infrastructure.ai_priority.metrics"


_metrics_snapshot.__module__ = "app.infrastructure.ai_priority.metrics"


_histogram_snapshot.__module__ = "app.infrastructure.ai_priority.metrics"


_percentile.__module__ = "app.infrastructure.ai_priority.metrics"
