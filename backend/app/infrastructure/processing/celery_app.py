"""Celery application for passport OCR processing."""

from __future__ import annotations

from celery import Celery

from app.core.config.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "passdetection",
    broker=settings.redis.url,
    backend=settings.redis.url,
    include=[
        "app.infrastructure.processing.tasks",
        "app.infrastructure.whatsapp.tasks",
    ],
)

celery_app.conf.update(
    task_default_queue="passport_ocr",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)
