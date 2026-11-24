"""Bounded synchronous probes for existing runtime dependencies."""

from __future__ import annotations

from redis import Redis

from app.core.config.settings import Settings
from app.infrastructure.ai_priority.worker_readiness import celery_queue_readiness
from app.infrastructure.ecr import ECR_QUEUE
from app.infrastructure.my_photos import (
    MY_PHOTOS_CONTROL_QUEUE,
    MY_PHOTOS_INDEX_QUEUE,
    MY_PHOTOS_MEDIA_QUEUE,
    MY_PHOTOS_SEARCH_QUEUE,
)
from app.infrastructure.my_photos.providers import build_provider_bundle
from app.infrastructure.runtime_readiness_contracts import (
    GENERAL_PROCESSING_QUEUE,
    PLATFORM_SCHEDULER_HEARTBEAT_KEY,
)
from app.infrastructure.security.upload_validator import (
    ClamAVMalwareScanner,
    malware_scanner_from_settings,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository


def _probe_ecr_worker(settings: Settings) -> tuple[str, bool]:
    if settings.processing_backend != "celery":
        return "worker_backend_not_celery", False
    return celery_queue_readiness(ECR_QUEUE, settings)


def _security_redis_required(settings: Settings) -> bool:
    return any(
        (
            settings.dashboard_rate_limit_require_redis,
            settings.login_lockout_require_redis,
            settings.public_upload_rate_limit_require_redis,
        )
    )


def _probe_security_redis(settings: Settings) -> tuple[str, bool]:
    if not _security_redis_required(settings):
        return "not_required", True
    client = Redis.from_url(
        settings.redis.security_url,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )
    try:
        return ("available", True) if client.ping() else ("unreachable", False)
    finally:
        client.close()  # type: ignore[no-untyped-call]


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
        providers.liveness.ready and providers.face_search.ready and providers.media.ready
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
