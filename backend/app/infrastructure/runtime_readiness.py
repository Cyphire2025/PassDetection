"""Bounded, cached readiness for infrastructure-backed app capabilities.

The public readiness route should answer whether this process can safely admit
traffic; it must not create buckets, mutate schema, or turn every load-balancer
probe into a fan-out storm. Slow network probes are therefore parallel,
deadline-bounded, and cached per process. Database checks remain lightweight
and authoritative on every request.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from redis import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.infrastructure.ai_priority.worker_readiness import celery_queue_readiness
from app.infrastructure.my_photos import (
    MY_PHOTOS_CONTROL_QUEUE,
    MY_PHOTOS_INDEX_QUEUE,
    MY_PHOTOS_MEDIA_QUEUE,
    MY_PHOTOS_SEARCH_QUEUE,
)
from app.infrastructure.my_photos.providers import build_provider_bundle
from app.infrastructure.security.upload_validator import (
    ClamAVMalwareScanner,
    malware_scanner_from_settings,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository

GENERAL_PROCESSING_QUEUE = "passport_ocr"
PLATFORM_SCHEDULER_HEARTBEAT_KEY = (
    "passdetection:platform:scheduler-heartbeat:v1"
)
READINESS_CACHE_SECONDS = 15.0
READINESS_REFRESH_TIMEOUT_SECONDS = 3.5
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
    object_storage_ready: bool
    malware_ready: bool
    general_worker_ready: bool
    scheduler_ready: bool
    my_photos_ready: bool
    my_photos_required: bool


@dataclass(frozen=True, slots=True)
class _CleanupBacklog:
    due_count: int
    blocked_count: int
    oldest_due_seconds: int


class RuntimeReadinessProbe:
    """Process-local readiness probe with configuration-aware TTL caching."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        cache_seconds: float = READINESS_CACHE_SECONDS,
        refresh_timeout_seconds: float = READINESS_REFRESH_TIMEOUT_SECONDS,
    ) -> None:
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._refresh_timeout_seconds = refresh_timeout_seconds
        self._cache_lock = threading.Lock()
        self._cache_key: tuple[object, ...] | None = None
        self._cache_expires_at = 0.0
        self._cached: _BlockingSnapshot | None = None

    async def snapshot(
        self,
        *,
        db: AsyncSession,
        settings: Settings,
    ) -> RuntimeCapabilitySnapshot:
        schema_status, schema_ready = await _schema_readiness(db, settings)
        cleanup = await _cleanup_backlog(db)
        blocking = await self._blocking_snapshot(settings)

        cleanup_ready = (
            cleanup.blocked_count == 0
            and cleanup.oldest_due_seconds <= STORAGE_CLEANUP_CRITICAL_AGE_SECONDS
        )
        if cleanup.blocked_count:
            cleanup_status = f"blocked_jobs:{cleanup.blocked_count}"
        elif cleanup.oldest_due_seconds > STORAGE_CLEANUP_CRITICAL_AGE_SECONDS:
            cleanup_status = "oldest_due_over_24h"
        elif cleanup.due_count >= STORAGE_CLEANUP_WARNING_COUNT:
            cleanup_status = f"backlog_warning:{cleanup.due_count}"
        else:
            cleanup_status = f"ok:{cleanup.due_count}"

        checks = {
            "database_schema": schema_status,
            "storage_cleanup_backlog": cleanup_status,
            **blocking.checks,
        }
        core_ready = all(
            (
                schema_ready,
                blocking.object_storage_ready,
                blocking.malware_ready,
                blocking.general_worker_ready,
                blocking.scheduler_ready,
            )
        )
        capabilities = {
            "object_storage": _capability(
                required=True,
                available=blocking.object_storage_ready,
                traffic_gate=True,
                status=blocking.checks["object_storage"],
            ),
            "document_ingestion": _capability(
                required=settings.untrusted_document_ingestion_enabled,
                available=blocking.malware_ready,
                traffic_gate=settings.untrusted_document_ingestion_enabled,
                status=blocking.checks["malware_scanner"],
            ),
            "background_processing": _capability(
                required=settings.processing_backend == "celery",
                available=blocking.general_worker_ready,
                traffic_gate=settings.processing_backend == "celery",
                status=blocking.checks["general_processing_worker"],
            ),
            "lifecycle_scheduler": _capability(
                required=settings.processing_backend == "celery",
                available=blocking.scheduler_ready,
                traffic_gate=settings.processing_backend == "celery",
                status=blocking.checks["platform_scheduler"],
            ),
            "database_schema": _capability(
                required=True,
                available=schema_ready,
                traffic_gate=True,
                status=schema_status,
            ),
            "storage_cleanup": _capability(
                required=True,
                available=cleanup_ready,
                traffic_gate=False,
                status=cleanup_status,
            ),
            "my_photos": _capability(
                required=blocking.my_photos_required,
                available=blocking.my_photos_ready,
                traffic_gate=False,
                status=blocking.checks["my_photos"],
            ),
        }
        return RuntimeCapabilitySnapshot(
            checks=checks,
            core_ready=core_ready,
            capabilities=capabilities,
        )

    async def _blocking_snapshot(self, settings: Settings) -> _BlockingSnapshot:
        key = _settings_cache_key(settings)
        now = self._clock()
        with self._cache_lock:
            if (
                self._cached is not None
                and self._cache_key == key
                and now < self._cache_expires_at
            ):
                return self._cached

        try:
            refreshed = await asyncio.wait_for(
                _refresh_blocking_capabilities(settings),
                timeout=self._refresh_timeout_seconds,
            )
        except TimeoutError:
            refreshed = _timed_out_snapshot(settings)

        with self._cache_lock:
            self._cached = refreshed
            self._cache_key = key
            self._cache_expires_at = self._clock() + self._cache_seconds
        return refreshed


async def _schema_readiness(
    db: AsyncSession,
    settings: Settings,
) -> tuple[str, bool]:
    try:
        result = await db.execute(
            text("SELECT version_num FROM alembic_version ORDER BY version_num")
        )
        versions = tuple(str(value) for value in result.scalars().all())
    except Exception:
        return "unavailable", False
    expected = settings.expected_database_schema_revision
    if versions == (expected,):
        return "compatible", True
    if not versions:
        return "missing", False
    if len(versions) > 1:
        return "multiple_heads", False
    return "revision_mismatch", False


async def _cleanup_backlog(db: AsyncSession) -> _CleanupBacklog:
    try:
        result = await db.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE status IN ('pending', 'running')
                          AND next_attempt_at <= CURRENT_TIMESTAMP
                    ) AS due_count,
                    COUNT(*) FILTER (WHERE status = 'blocked') AS blocked_count,
                    COALESCE(
                        EXTRACT(EPOCH FROM (
                            CURRENT_TIMESTAMP - MIN(created_at) FILTER (
                                WHERE status IN ('pending', 'running')
                                  AND next_attempt_at <= CURRENT_TIMESTAMP
                            )
                        )),
                        0
                    ) AS oldest_due_seconds
                FROM storage_cleanup_jobs
                """
            )
        )
        row = result.mappings().one()
        return _CleanupBacklog(
            due_count=max(0, int(row["due_count"] or 0)),
            blocked_count=max(0, int(row["blocked_count"] or 0)),
            oldest_due_seconds=max(0, int(row["oldest_due_seconds"] or 0)),
        )
    except Exception:
        # A missing/unreadable cleanup table is itself visible degradation. It
        # is not a second traffic gate because schema readiness already fails
        # closed for incompatible deployments.
        return _CleanupBacklog(
            due_count=0,
            blocked_count=1,
            oldest_due_seconds=0,
        )


async def _refresh_blocking_capabilities(settings: Settings) -> _BlockingSnapshot:
    storage_result, scanner_result, runtime_result, provider_result = await asyncio.gather(
        asyncio.to_thread(_probe_object_storage),
        asyncio.to_thread(_probe_malware_scanner, settings),
        asyncio.to_thread(_probe_worker_and_scheduler, settings),
        asyncio.to_thread(_probe_my_photos, settings),
        return_exceptions=True,
    )

    storage_ready = storage_result is True
    malware_status, malware_ready = _probe_result(
        scanner_result,
        failure_status="unreachable",
    )
    if not isinstance(runtime_result, tuple):
        worker_status, worker_ready = "probe_failed", False
        scheduler_status, scheduler_ready = "probe_failed", False
    else:
        worker_status, worker_ready, scheduler_status, scheduler_ready = runtime_result

    if not isinstance(provider_result, tuple):
        my_photos_status, my_photos_ready, my_photos_required = (
            "probe_failed",
            False,
            _my_photos_selected(settings),
        )
    else:
        my_photos_status, my_photos_ready, my_photos_required = provider_result

    return _BlockingSnapshot(
        checks={
            "object_storage": "available" if storage_ready else "unreachable",
            "malware_scanner": malware_status,
            "general_processing_worker": worker_status,
            "platform_scheduler": scheduler_status,
            "my_photos": my_photos_status,
        },
        object_storage_ready=storage_ready,
        malware_ready=malware_ready,
        general_worker_ready=worker_ready,
        scheduler_ready=scheduler_ready,
        my_photos_ready=my_photos_ready,
        my_photos_required=my_photos_required,
    )


def _probe_object_storage() -> bool:
    MinioStorageRepository().check_bucket_access()
    return True


def _probe_malware_scanner(settings: Settings) -> tuple[str, bool]:
    if not settings.untrusted_document_ingestion_enabled:
        return "not_required_ingestion_disabled", True
    scanner = malware_scanner_from_settings(settings)
    if not isinstance(scanner, ClamAVMalwareScanner):
        if settings.is_development:
            return "development_bypass", True
        return "not_configured", False
    scanner.healthcheck()
    return "available", True


def _probe_worker_and_scheduler(
    settings: Settings,
) -> tuple[str, bool, str, bool]:
    if settings.processing_backend != "celery":
        status = "not_required_background_backend"
        return status, True, status, True
    worker_status, worker_ready = celery_queue_readiness(
        GENERAL_PROCESSING_QUEUE,
        settings,
    )
    scheduler_ready = _platform_scheduler_heartbeat_exists(settings)
    scheduler_status = "heartbeat_recent" if scheduler_ready else "heartbeat_missing"
    return worker_status, worker_ready, scheduler_status, scheduler_ready


def _probe_my_photos(settings: Settings) -> tuple[str, bool, bool]:
    if not _my_photos_selected(settings):
        return "not_required_feature_disabled", True, False

    providers = build_provider_bundle(settings)
    providers_ready = (
        providers.liveness.ready
        and providers.face_search.ready
        and providers.media.ready
    )
    if not providers_ready:
        return "providers_not_ready", False, True
    if settings.processing_backend != "celery":
        return "worker_backend_not_celery", False, True

    statuses = [
        celery_queue_readiness(queue, settings)
        for queue in (
            MY_PHOTOS_CONTROL_QUEUE,
            MY_PHOTOS_INDEX_QUEUE,
            MY_PHOTOS_MEDIA_QUEUE,
            MY_PHOTOS_SEARCH_QUEUE,
        )
    ]
    if all(ready for _status, ready in statuses):
        return "available", True, True
    missing = sum(not ready for _status, ready in statuses)
    return f"queues_unavailable:{missing}", False, True


def _platform_scheduler_heartbeat_exists(settings: Settings) -> bool:
    timeout = min(settings.processing_worker_ping_timeout_seconds, 1.0)
    client = Redis.from_url(
        settings.redis.broker_url,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
        decode_responses=True,
    )
    try:
        return bool(client.get(PLATFORM_SCHEDULER_HEARTBEAT_KEY))
    finally:
        client.close()  # type: ignore[no-untyped-call]  # redis 5.0.7 omits this annotation


def _my_photos_selected(settings: Settings) -> bool:
    config = settings.my_photos
    return any(
        provider != "disabled"
        for provider in (
            config.liveness_provider,
            config.face_search_provider,
            config.media_provider,
        )
    )


def _probe_result(
    result: object,
    *,
    failure_status: str,
) -> tuple[str, bool]:
    if isinstance(result, tuple) and len(result) == 2:
        status, ready = result
        if isinstance(status, str) and isinstance(ready, bool):
            return status, ready
    return failure_status, False


def _settings_cache_key(settings: Settings) -> tuple[object, ...]:
    my_photos = settings.my_photos
    return (
        settings.app_env,
        settings.processing_backend,
        settings.untrusted_document_ingestion_enabled,
        settings.malware_scanner_enabled,
        settings.malware_scanner_host,
        settings.malware_scanner_port,
        settings.s3.endpoint_url,
        settings.s3.bucket_name,
        my_photos.liveness_provider,
        my_photos.face_search_provider,
        my_photos.media_provider,
    )


def _timed_out_snapshot(settings: Settings) -> _BlockingSnapshot:
    my_photos_required = _my_photos_selected(settings)
    return _BlockingSnapshot(
        checks={
            "object_storage": "probe_timeout",
            "malware_scanner": "probe_timeout",
            "general_processing_worker": "probe_timeout",
            "platform_scheduler": "probe_timeout",
            "my_photos": (
                "probe_timeout"
                if my_photos_required
                else "not_required_feature_disabled"
            ),
        },
        object_storage_ready=False,
        malware_ready=False,
        general_worker_ready=False,
        scheduler_ready=False,
        my_photos_ready=not my_photos_required,
        my_photos_required=my_photos_required,
    )


def _capability(
    *,
    required: bool,
    available: bool,
    traffic_gate: bool,
    status: str,
) -> dict[str, object]:
    return {
        "required": required,
        "available": available,
        "traffic_gate": traffic_gate,
        "status": status,
    }


_runtime_probe = RuntimeReadinessProbe()


async def runtime_capability_readiness(
    *,
    db: AsyncSession,
    settings: Settings,
) -> RuntimeCapabilitySnapshot:
    return await _runtime_probe.snapshot(db=db, settings=settings)


__all__ = [
    "GENERAL_PROCESSING_QUEUE",
    "PLATFORM_SCHEDULER_HEARTBEAT_KEY",
    "RuntimeCapabilitySnapshot",
    "RuntimeReadinessProbe",
    "runtime_capability_readiness",
]
