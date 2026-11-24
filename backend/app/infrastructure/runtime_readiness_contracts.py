"""Immutable runtime capability snapshots and reviewed readiness thresholds."""

from __future__ import annotations

from dataclasses import dataclass

GENERAL_PROCESSING_QUEUE = "passport_ocr"


PLATFORM_SCHEDULER_HEARTBEAT_KEY = "passdetection:platform:scheduler-heartbeat:v1"


READINESS_CACHE_SECONDS = 15.0


READINESS_REFRESH_TIMEOUT_SECONDS = 3.5


BLOCKING_PROBE_TIMEOUT_SECONDS = 3.0


STORAGE_CLEANUP_WARNING_COUNT = 1_000


STORAGE_CLEANUP_CRITICAL_AGE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class RuntimeCapabilitySnapshot:
    checks: dict[str, str]
    core_ready: bool
    capabilities: dict[str, dict[str, object]]


@dataclass(frozen=True, slots=True)
class _BlockingSnapshot:
    checks: dict[str, str]
    security_ready: bool
    object_storage_ready: bool
    malware_ready: bool
    general_worker_ready: bool
    scheduler_ready: bool
    my_photos_ready: bool
    my_photos_required: bool
    ecr_worker: tuple[str, bool] = ("probe_failed", False)


@dataclass(frozen=True, slots=True)
class _CleanupBacklog:
    due_count: int
    blocked_count: int
    oldest_due_seconds: int
