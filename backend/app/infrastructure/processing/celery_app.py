"""Celery application for passport OCR processing."""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from kombu import Queue

from app.core.config.settings import get_settings
from app.infrastructure.ai_priority import EXTRACTION_QUEUE, VERIFICATION_QUEUE
from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.mobile_push import (
    MOBILE_PUSH_COUNTDOWN_TASK,
    MOBILE_PUSH_DISPATCH_TASK,
    MOBILE_PUSH_RECEIPT_TASK,
)
from app.infrastructure.my_photos import (
    MY_PHOTOS_CONTROL_QUEUE,
    MY_PHOTOS_INDEX_QUEUE,
    MY_PHOTOS_INDEX_TASK,
    MY_PHOTOS_MEDIA_QUEUE,
    MY_PHOTOS_MEDIA_TASK,
    MY_PHOTOS_RECOVERY_TASK,
    MY_PHOTOS_SEARCH_QUEUE,
    MY_PHOTOS_SEARCH_TASK,
)
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.observability.statsd import configure_metrics_export
from app.infrastructure.visa_ai_image_jobs import (
    VISA_AI_IMAGE_QUEUE,
    VISA_AI_IMAGE_TASK,
)

EMAIL_INTEGRATION_QUEUE = "email_integrations"
EMAIL_AI_QUEUE = "email_ai"
EMAIL_SYNC_TASK = "email.sync_connection"
EMAIL_DISPATCH_TASK = "email.dispatch_due_connections"
EMAIL_RETENTION_TASK = "email.apply_retention"
EMAIL_SCHEDULER_HEARTBEAT_TASK = "email.scheduler_heartbeat"
EMAIL_AI_ANALYZE_TASK = "email.analyze_travel_message"
EMAIL_AI_DISPATCH_TASK = "email.dispatch_ai_analyses"
EMAIL_AI_DEADLINE_SCAN_TASK = "email.notify_ai_deadline_window"
DOCUMENT_STORAGE_CLEANUP_TASK = "documents.cleanup_storage"
DOCUMENT_STORAGE_ORPHAN_RECONCILIATION_TASK = "documents.reconcile_storage_orphans"
PLATFORM_LIFECYCLE_TASK = "platform.apply_lifecycle_policies"
PLATFORM_SCHEDULER_HEARTBEAT_TASK = "platform.scheduler_heartbeat"
COORDINATOR_ASSIGNMENT_EXPIRY_TASK = "coordinators.expire_trip_assignments"
IDENTITY_RECOVERY_DELIVERY_TASK = "identity.deliver_recovery_notifications"
IDENTITY_RETENTION_TASK = "identity.apply_retention"
WHATSAPP_BROADCAST_TASK = "whatsapp.process_broadcast"
WHATSAPP_DOCUMENT_BROADCAST_TASK = "whatsapp.process_document_broadcast"
WHATSAPP_QR_BROADCAST_TASK = "whatsapp.process_qr_broadcast"

# A task-specific provider timeout remains the first line of defence. These
# worker envelopes are the final process-level circuit breaker for bugs,
# parser hangs, or SDK calls that ignore cancellation. Soft limits permit
# cleanup/logging; hard limits guarantee worker capacity is eventually freed.
DEFAULT_TASK_SOFT_TIME_LIMIT_SECONDS = 14 * 60
DEFAULT_TASK_TIME_LIMIT_SECONDS = 15 * 60
WORKER_MAX_TASKS_PER_CHILD = 100
WORKER_MAX_MEMORY_PER_CHILD_KIB = 768 * 1024

settings = get_settings()

celery_app = Celery(
    "passdetection",
    broker=settings.redis.broker_url,
    backend=settings.redis.broker_url,
    include=[
        "app.infrastructure.processing.tasks",
        "app.infrastructure.verification.tasks",
        "app.infrastructure.visa_ai_image_jobs.tasks",
        "app.infrastructure.whatsapp.tasks",
        "app.infrastructure.email.tasks",
        "app.infrastructure.email.ai_tasks",
        "app.infrastructure.documents.cleanup_tasks",
        "app.infrastructure.platform_lifecycle_tasks",
        "app.infrastructure.coordinator_assignment_tasks",
        "app.infrastructure.security.identity_tasks",
        "app.infrastructure.mobile_push.tasks",
        "app.infrastructure.my_photos.tasks",
    ],
)

celery_app.conf.update(
    task_default_queue="passport_ocr",
    task_queues=(
        Queue("passport_ocr", durable=True),
        Queue("whatsapp", durable=True),
        Queue(EXTRACTION_QUEUE, durable=True),
        Queue(VERIFICATION_QUEUE, durable=True),
        Queue(VISA_AI_IMAGE_QUEUE, durable=True),
        Queue(EMAIL_INTEGRATION_QUEUE, durable=True),
        Queue(EMAIL_AI_QUEUE, durable=True),
        Queue(MY_PHOTOS_INDEX_QUEUE, durable=True),
        Queue(MY_PHOTOS_CONTROL_QUEUE, durable=True),
        Queue(MY_PHOTOS_MEDIA_QUEUE, durable=True),
        Queue(MY_PHOTOS_SEARCH_QUEUE, durable=True),
    ),
    task_routes={
        "passport.process_submission": {"queue": EXTRACTION_QUEUE},
        "passport.verify_submitted": {"queue": VERIFICATION_QUEUE},
        VISA_AI_IMAGE_TASK: {"queue": VISA_AI_IMAGE_QUEUE},
        EMAIL_SYNC_TASK: {"queue": EMAIL_INTEGRATION_QUEUE},
        EMAIL_DISPATCH_TASK: {"queue": EMAIL_INTEGRATION_QUEUE},
        EMAIL_RETENTION_TASK: {"queue": EMAIL_INTEGRATION_QUEUE},
        EMAIL_SCHEDULER_HEARTBEAT_TASK: {"queue": EMAIL_INTEGRATION_QUEUE},
        EMAIL_AI_ANALYZE_TASK: {"queue": EMAIL_AI_QUEUE},
        EMAIL_AI_DISPATCH_TASK: {"queue": EMAIL_INTEGRATION_QUEUE},
        EMAIL_AI_DEADLINE_SCAN_TASK: {"queue": EMAIL_INTEGRATION_QUEUE},
        DOCUMENT_STORAGE_CLEANUP_TASK: {"queue": "passport_ocr"},
        DOCUMENT_STORAGE_ORPHAN_RECONCILIATION_TASK: {"queue": "passport_ocr"},
        PLATFORM_LIFECYCLE_TASK: {"queue": "passport_ocr"},
        COORDINATOR_ASSIGNMENT_EXPIRY_TASK: {"queue": "passport_ocr"},
        IDENTITY_RECOVERY_DELIVERY_TASK: {"queue": "passport_ocr"},
        IDENTITY_RETENTION_TASK: {"queue": "passport_ocr"},
        WHATSAPP_BROADCAST_TASK: {"queue": "whatsapp"},
        WHATSAPP_DOCUMENT_BROADCAST_TASK: {"queue": "whatsapp"},
        WHATSAPP_QR_BROADCAST_TASK: {"queue": "whatsapp"},
        MOBILE_PUSH_COUNTDOWN_TASK: {"queue": "passport_ocr"},
        MOBILE_PUSH_DISPATCH_TASK: {"queue": "passport_ocr"},
        MOBILE_PUSH_RECEIPT_TASK: {"queue": "passport_ocr"},
        MY_PHOTOS_SEARCH_TASK: {"queue": MY_PHOTOS_SEARCH_QUEUE},
        MY_PHOTOS_INDEX_TASK: {"queue": MY_PHOTOS_INDEX_QUEUE},
        MY_PHOTOS_MEDIA_TASK: {"queue": MY_PHOTOS_MEDIA_QUEUE},
        MY_PHOTOS_RECOVERY_TASK: {"queue": MY_PHOTOS_CONTROL_QUEUE},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=DEFAULT_TASK_SOFT_TIME_LIMIT_SECONDS,
    task_time_limit=DEFAULT_TASK_TIME_LIMIT_SECONDS,
    task_track_started=True,
    worker_max_tasks_per_child=WORKER_MAX_TASKS_PER_CHILD,
    worker_max_memory_per_child=WORKER_MAX_MEMORY_PER_CHILD_KIB,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    task_annotations={
        # Interactive work should release capacity well before the global
        # poison-job envelope. Durable job rows own retry/dead-letter state.
        "passport.process_submission": {
            "soft_time_limit": 9 * 60,
            "time_limit": 10 * 60,
        },
        "passport.verify_submitted": {
            "soft_time_limit": 9 * 60,
            "time_limit": 10 * 60,
        },
        VISA_AI_IMAGE_TASK: {
            "soft_time_limit": 9 * 60,
            "time_limit": 10 * 60,
        },
        EMAIL_SYNC_TASK: {
            "soft_time_limit": 9 * 60,
            "time_limit": 10 * 60,
        },
        EMAIL_AI_ANALYZE_TASK: {
            "soft_time_limit": 9 * 60,
            "time_limit": 10 * 60,
        },
        EMAIL_AI_DISPATCH_TASK: {
            "soft_time_limit": 4 * 60,
            "time_limit": 5 * 60,
        },
        EMAIL_AI_DEADLINE_SCAN_TASK: {
            "soft_time_limit": 4 * 60,
            "time_limit": 5 * 60,
        },
        EMAIL_DISPATCH_TASK: {
            "soft_time_limit": 4 * 60,
            "time_limit": 5 * 60,
        },
        EMAIL_RETENTION_TASK: {
            "soft_time_limit": 9 * 60,
            "time_limit": 10 * 60,
        },
        EMAIL_SCHEDULER_HEARTBEAT_TASK: {
            "soft_time_limit": 60,
            "time_limit": 90,
        },
        WHATSAPP_BROADCAST_TASK: {
            "soft_time_limit": 9 * 60,
            "time_limit": 10 * 60,
        },
        WHATSAPP_DOCUMENT_BROADCAST_TASK: {
            "soft_time_limit": 9 * 60,
            "time_limit": 10 * 60,
        },
        WHATSAPP_QR_BROADCAST_TASK: {
            "soft_time_limit": 9 * 60,
            "time_limit": 10 * 60,
        },
        DOCUMENT_STORAGE_CLEANUP_TASK: {
            "soft_time_limit": 4 * 60,
            "time_limit": 5 * 60,
        },
        DOCUMENT_STORAGE_ORPHAN_RECONCILIATION_TASK: {
            "soft_time_limit": 9 * 60,
            "time_limit": 10 * 60,
        },
        PLATFORM_LIFECYCLE_TASK: {
            "soft_time_limit": 9 * 60,
            "time_limit": 10 * 60,
        },
        COORDINATOR_ASSIGNMENT_EXPIRY_TASK: {
            "soft_time_limit": 45,
            "time_limit": 60,
        },
        MOBILE_PUSH_COUNTDOWN_TASK: {
            "soft_time_limit": 4 * 60,
            "time_limit": 5 * 60,
        },
        MOBILE_PUSH_DISPATCH_TASK: {
            "soft_time_limit": 4 * 60,
            "time_limit": 5 * 60,
        },
        MOBILE_PUSH_RECEIPT_TASK: {
            "soft_time_limit": 4 * 60,
            "time_limit": 5 * 60,
        },
        MY_PHOTOS_SEARCH_TASK: {
            # Must remain below MY_PHOTOS_JOB_LEASE_SECONDS' minimum (90s),
            # otherwise a killed worker can outlive its lease contract.
            "soft_time_limit": 65,
            "time_limit": 75,
        },
        MY_PHOTOS_INDEX_TASK: {
            "soft_time_limit": 65,
            "time_limit": 75,
        },
        MY_PHOTOS_MEDIA_TASK: {
            "soft_time_limit": 65,
            "time_limit": 75,
        },
        MY_PHOTOS_RECOVERY_TASK: {
            "soft_time_limit": 210,
            "time_limit": 240,
        },
    },
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "dispatch-due-email-connections": {
            "task": EMAIL_DISPATCH_TASK,
            "schedule": 5.0,
            "options": {"queue": EMAIL_INTEGRATION_QUEUE},
        },
        "apply-email-content-retention": {
            "task": EMAIL_RETENTION_TASK,
            "schedule": 86_400.0,
            "options": {"queue": EMAIL_INTEGRATION_QUEUE},
        },
        "record-email-scheduler-heartbeat": {
            "task": EMAIL_SCHEDULER_HEARTBEAT_TASK,
            "schedule": 60.0,
            "options": {"queue": EMAIL_INTEGRATION_QUEUE},
        },
        "dispatch-travel-email-analyses": {
            "task": EMAIL_AI_DISPATCH_TASK,
            "schedule": 5.0,
            "options": {"queue": EMAIL_INTEGRATION_QUEUE},
        },
        "notify-travel-email-deadline-window": {
            "task": EMAIL_AI_DEADLINE_SCAN_TASK,
            "schedule": 60.0,
            "options": {"queue": EMAIL_INTEGRATION_QUEUE},
        },
        "cleanup-deferred-document-storage": {
            "task": DOCUMENT_STORAGE_CLEANUP_TASK,
            "schedule": 60.0,
            "options": {"queue": "passport_ocr"},
        },
        "reconcile-orphaned-document-storage": {
            "task": DOCUMENT_STORAGE_ORPHAN_RECONCILIATION_TASK,
            "schedule": 3_600.0,
            "options": {"queue": "passport_ocr"},
        },
        "apply-platform-lifecycle-policies": {
            "task": PLATFORM_LIFECYCLE_TASK,
            "schedule": 86_400.0,
            "options": {"queue": "passport_ocr"},
        },
        "expire-ended-trip-coordinator-assignments": {
            "task": COORDINATOR_ASSIGNMENT_EXPIRY_TASK,
            "schedule": 60.0,
            "options": {"queue": "passport_ocr", "expires": 60},
        },
        "record-platform-scheduler-heartbeat": {
            "task": PLATFORM_SCHEDULER_HEARTBEAT_TASK,
            "schedule": 15.0,
            "options": {"queue": "passport_ocr"},
        },
        "deliver-password-recovery-notifications": {
            "task": IDENTITY_RECOVERY_DELIVERY_TASK,
            "schedule": 10.0,
            "options": {"queue": "passport_ocr"},
        },
        "apply-identity-record-retention": {
            "task": IDENTITY_RETENTION_TASK,
            "schedule": 86_400.0,
            "options": {"queue": "passport_ocr"},
        },
        "dispatch-mobile-push-notifications": {
            "task": MOBILE_PUSH_DISPATCH_TASK,
            "schedule": settings.mobile.push_dispatch_interval_seconds,
            "options": {"queue": "passport_ocr"},
        },
        "schedule-mobile-trip-countdowns": {
            "task": MOBILE_PUSH_COUNTDOWN_TASK,
            "schedule": settings.mobile.push_countdown_scan_interval_seconds,
            "options": {"queue": "passport_ocr"},
        },
        "reconcile-mobile-push-receipts": {
            "task": MOBILE_PUSH_RECEIPT_TASK,
            "schedule": settings.mobile.push_receipt_poll_interval_seconds,
            "options": {"queue": "passport_ocr"},
        },
        "recover-my-photos-durable-jobs": {
            "task": MY_PHOTOS_RECOVERY_TASK,
            "schedule": 30.0,
            "options": {"queue": MY_PHOTOS_CONTROL_QUEUE},
        },
    },
)


@worker_process_init.connect(weak=False)  # type: ignore[untyped-decorator]
def initialize_worker_async_runtime(**_: object) -> None:
    """Create loop-bound resources only after the prefork child starts."""

    configure_metrics_export(settings)
    celery_async_runtime.initialize()


@worker_process_shutdown.connect(weak=False)  # type: ignore[untyped-decorator]
def shutdown_worker_async_runtime(**_: object) -> None:
    """Close the process-local loop and its pooled database connections."""

    celery_async_runtime.shutdown()
    metrics.close_export_sink()
