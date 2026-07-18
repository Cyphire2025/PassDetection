"""Celery application for passport OCR processing."""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from app.core.config.settings import get_settings
from app.infrastructure.ai_priority import EXTRACTION_QUEUE, VERIFICATION_QUEUE

settings = get_settings()

celery_app = Celery(
    "passdetection",
    broker=settings.redis.url,
    backend=settings.redis.url,
    include=[
        "app.infrastructure.processing.tasks",
        "app.infrastructure.verification.tasks",
        "app.infrastructure.whatsapp.tasks",
    ],
)

celery_app.conf.update(
    task_default_queue="passport_ocr",
    task_queues=(
        Queue("passport_ocr", durable=True),
        Queue("whatsapp", durable=True),
        Queue(EXTRACTION_QUEUE, durable=True),
        Queue(VERIFICATION_QUEUE, durable=True),
    ),
    task_routes={
        "passport.process_submission": {"queue": EXTRACTION_QUEUE},
        "passport.verify_submitted": {"queue": VERIFICATION_QUEUE},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)
