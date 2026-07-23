"""Celery dispatch helpers for durable Visa-photo AI generation jobs."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.core.logging.logger import get_logger
from app.infrastructure.visa_ai_image_jobs import VISA_AI_IMAGE_QUEUE

logger = get_logger(__name__)


def _send_job(*, job_id: uuid.UUID, submission_id: uuid.UUID) -> Any:
    from app.infrastructure.visa_ai_image_jobs.tasks import generate_visa_ai_image

    return generate_visa_ai_image.apply_async(
        kwargs={
            "job_id": str(job_id),
            "submission_id": str(submission_id),
        },
        queue=VISA_AI_IMAGE_QUEUE,
    )


async def dispatch_visa_ai_image_job(
    *,
    job_id: uuid.UUID,
    submission_id: uuid.UUID,
) -> str | None:
    """Publish without blocking the request event loop.

    The database row is the durable source of truth. A broker outage therefore
    leaves a queued job that a later status poll can safely publish again.
    """

    try:
        task = await asyncio.to_thread(
            _send_job,
            job_id=job_id,
            submission_id=submission_id,
        )
    except Exception as exc:
        logger.warning(
            "visa_ai_image_job_dispatch_failed",
            job_id=str(job_id),
            submission_id=str(submission_id),
            error_type=type(exc).__name__,
        )
        return None
    return str(task.id)
