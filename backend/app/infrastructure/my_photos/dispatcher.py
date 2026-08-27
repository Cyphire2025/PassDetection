"""Post-commit dispatch helpers for My Photos durable jobs."""

from __future__ import annotations

import uuid

from app.infrastructure.my_photos import (
    MY_PHOTOS_INDEX_QUEUE,
    MY_PHOTOS_INDEX_TASK,
    MY_PHOTOS_MEDIA_QUEUE,
    MY_PHOTOS_MEDIA_TASK,
    MY_PHOTOS_SEARCH_QUEUE,
    MY_PHOTOS_SEARCH_TASK,
)
from app.infrastructure.processing.celery_app import celery_app


def enqueue_search_job(search_run_id: uuid.UUID) -> None:
    celery_app.send_task(
        MY_PHOTOS_SEARCH_TASK,
        args=[str(search_run_id)],
        queue=MY_PHOTOS_SEARCH_QUEUE,
    )


def enqueue_index_job(job_id: uuid.UUID) -> None:
    celery_app.send_task(
        MY_PHOTOS_INDEX_TASK,
        args=[str(job_id)],
        queue=MY_PHOTOS_INDEX_QUEUE,
    )


def enqueue_media_job(job_id: uuid.UUID) -> None:
    celery_app.send_task(
        MY_PHOTOS_MEDIA_TASK,
        args=[str(job_id)],
        queue=MY_PHOTOS_MEDIA_QUEUE,
    )


__all__ = ["enqueue_index_job", "enqueue_media_job", "enqueue_search_job"]
