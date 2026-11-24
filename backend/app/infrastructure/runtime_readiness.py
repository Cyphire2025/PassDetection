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
from dataclasses import dataclass as dataclass

from redis import Redis as Redis
from sqlalchemy import text as text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.infrastructure.ai_priority.worker_readiness import (
    celery_queue_readiness as celery_queue_readiness,
)
from app.infrastructure.ecr import ECR_QUEUE as ECR_QUEUE
from app.infrastructure.ecr.readiness import ecr_backlog, ecr_capability
from app.infrastructure.my_photos import MY_PHOTOS_CONTROL_QUEUE as MY_PHOTOS_CONTROL_QUEUE
from app.infrastructure.my_photos import MY_PHOTOS_INDEX_QUEUE as MY_PHOTOS_INDEX_QUEUE
from app.infrastructure.my_photos import MY_PHOTOS_MEDIA_QUEUE as MY_PHOTOS_MEDIA_QUEUE
from app.infrastructure.my_photos import MY_PHOTOS_SEARCH_QUEUE as MY_PHOTOS_SEARCH_QUEUE
from app.infrastructure.my_photos.providers import build_provider_bundle as build_provider_bundle
from app.infrastructure.readiness_executor import (
    readiness_probe_executor as readiness_probe_executor,
)
from app.infrastructure.runtime_readiness_capabilities import _capability as _capability
from app.infrastructure.runtime_readiness_capabilities import _probe_result as _probe_result
from app.infrastructure.runtime_readiness_capabilities import (
    _refresh_blocking_capabilities as _refresh_blocking_capabilities,
)
from app.infrastructure.runtime_readiness_capabilities import (
    _timed_out_snapshot as _timed_out_snapshot,
)
from app.infrastructure.runtime_readiness_contracts import (
    BLOCKING_PROBE_TIMEOUT_SECONDS as BLOCKING_PROBE_TIMEOUT_SECONDS,
)
from app.infrastructure.runtime_readiness_contracts import (
    GENERAL_PROCESSING_QUEUE as GENERAL_PROCESSING_QUEUE,
)
from app.infrastructure.runtime_readiness_contracts import (
    PLATFORM_SCHEDULER_HEARTBEAT_KEY as PLATFORM_SCHEDULER_HEARTBEAT_KEY,
)
from app.infrastructure.runtime_readiness_contracts import (
    READINESS_CACHE_SECONDS as READINESS_CACHE_SECONDS,
)
from app.infrastructure.runtime_readiness_contracts import (
    READINESS_REFRESH_TIMEOUT_SECONDS as READINESS_REFRESH_TIMEOUT_SECONDS,
)
from app.infrastructure.runtime_readiness_contracts import (
    STORAGE_CLEANUP_CRITICAL_AGE_SECONDS as STORAGE_CLEANUP_CRITICAL_AGE_SECONDS,
)
from app.infrastructure.runtime_readiness_contracts import (
    STORAGE_CLEANUP_WARNING_COUNT as STORAGE_CLEANUP_WARNING_COUNT,
)
from app.infrastructure.runtime_readiness_contracts import (
    RuntimeCapabilitySnapshot as RuntimeCapabilitySnapshot,
)
from app.infrastructure.runtime_readiness_contracts import _BlockingSnapshot as _BlockingSnapshot
from app.infrastructure.runtime_readiness_contracts import _CleanupBacklog as _CleanupBacklog
from app.infrastructure.runtime_readiness_database import _cleanup_backlog as _cleanup_backlog
from app.infrastructure.runtime_readiness_database import _schema_readiness as _schema_readiness
from app.infrastructure.runtime_readiness_probes import _my_photos_selected as _my_photos_selected
from app.infrastructure.runtime_readiness_probes import (
    _platform_scheduler_heartbeat_exists as _platform_scheduler_heartbeat_exists,
)
from app.infrastructure.runtime_readiness_probes import _probe_ecr_worker as _probe_ecr_worker
from app.infrastructure.runtime_readiness_probes import (
    _probe_malware_scanner as _probe_malware_scanner,
)
from app.infrastructure.runtime_readiness_probes import _probe_my_photos as _probe_my_photos
from app.infrastructure.runtime_readiness_probes import (
    _probe_object_storage as _probe_object_storage,
)
from app.infrastructure.runtime_readiness_probes import (
    _probe_security_redis as _probe_security_redis,
)
from app.infrastructure.runtime_readiness_probes import (
    _probe_worker_and_scheduler as _probe_worker_and_scheduler,
)
from app.infrastructure.runtime_readiness_probes import (
    _security_redis_required as _security_redis_required,
)
from app.infrastructure.security.upload_validator import (
    ClamAVMalwareScanner as ClamAVMalwareScanner,
)
from app.infrastructure.security.upload_validator import (
    malware_scanner_from_settings as malware_scanner_from_settings,
)
from app.infrastructure.storage.minio_repository import (
    MinioStorageRepository as MinioStorageRepository,
)


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
        ecr = await ecr_backlog(db)

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
                blocking.security_ready,
                blocking.object_storage_ready,
                blocking.malware_ready,
                blocking.general_worker_ready,
                blocking.scheduler_ready,
            )
        )
        capabilities = {
            "ecr_checks": ecr_capability(blocking.ecr_worker, ecr),
            "request_protection": _capability(
                required=_security_redis_required(settings),
                available=blocking.security_ready,
                traffic_gate=_security_redis_required(settings),
                status=blocking.checks["security_redis"],
            ),
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
            if self._cached is not None and self._cache_key == key and now < self._cache_expires_at:
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


def _settings_cache_key(settings: Settings) -> tuple[object, ...]:
    my_photos = settings.my_photos
    return (
        settings.app_env,
        settings.redis.security_url,
        settings.dashboard_rate_limit_require_redis,
        settings.login_lockout_require_redis,
        settings.public_upload_rate_limit_require_redis,
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
