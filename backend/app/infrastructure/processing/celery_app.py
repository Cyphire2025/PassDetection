"""Celery application for passport OCR processing."""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from kombu import Queue

from app.core.config.settings import get_settings
from app.infrastructure.ai_priority import EXTRACTION_QUEUE, VERIFICATION_QUEUE
from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.visa_ai_image_jobs import (
    VISA_AI_IMAGE_QUEUE,
    VISA_AI_IMAGE_TASK,
)

EMAIL_INTEGRATION_QUEUE = "email_integrations"
EMAIL_SYNC_TASK = "email.sync_connection"
EMAIL_DISPATCH_TASK = "email.dispatch_due_connections"
EMAIL_RETENTION_TASK = "email.apply_retention"
EMAIL_SCHEDULER_HEARTBEAT_TASK = "email.scheduler_heartbeat"

settings = get_settings()

celery_app = Celery(
    "passdetection",
    broker=settings.redis.url,
    backend=settings.redis.url,
    include=[
        "app.infrastructure.processing.tasks",
        "app.infrastructure.verification.tasks",
        "app.infrastructure.visa_ai_image_jobs.tasks",
        "app.infrastructure.whatsapp.tasks",
        "app.infrastructure.email.tasks",
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
    ),
    task_routes={
        "passport.process_submission": {"queue": EXTRACTION_QUEUE},
        "passport.verify_submitted": {"queue": VERIFICATION_QUEUE},
        VISA_AI_IMAGE_TASK: {"queue": VISA_AI_IMAGE_QUEUE},
        EMAIL_SYNC_TASK: {"queue": EMAIL_INTEGRATION_QUEUE},
        EMAIL_DISPATCH_TASK: {"queue": EMAIL_INTEGRATION_QUEUE},
        EMAIL_RETENTION_TASK: {"queue": EMAIL_INTEGRATION_QUEUE},
        EMAIL_SCHEDULER_HEARTBEAT_TASK: {"queue": EMAIL_INTEGRATION_QUEUE},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
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
    },
)


@worker_process_init.connect(weak=False)  # type: ignore[untyped-decorator]
def initialize_worker_async_runtime(**_: object) -> None:
    """Create loop-bound resources only after the prefork child starts."""

    celery_async_runtime.initialize()


@worker_process_shutdown.connect(weak=False)  # type: ignore[untyped-decorator]
def shutdown_worker_async_runtime(**_: object) -> None:
    """Close the process-local loop and its pooled database connections."""

    celery_async_runtime.shutdown()
