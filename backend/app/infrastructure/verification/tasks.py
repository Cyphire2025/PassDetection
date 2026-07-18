"""Celery task for durable post-submit passport verification."""

from __future__ import annotations

import asyncio

from celery.exceptions import Reject

from app.core.config.settings import get_settings
from app.infrastructure.ai_priority import (
    VERIFICATION_QUEUE,
    AiPriorityAdmissionDeferred,
)
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.verification.runtime import (
    PostSubmissionVerificationRetryRequested,
    run_post_submission_verification,
)


@celery_app.task(
    bind=True,
    name="passport.verify_submitted",
    queue=VERIFICATION_QUEUE,
    max_retries=max(0, get_settings().processing_job_max_attempts - 1),
    default_retry_delay=5,
)
def verify_submitted_passport(
    self,  # type: ignore[no-untyped-def]
    *,
    job_id: str,
    submission_id: str,
    verification_revision: int,
) -> None:
    try:
        asyncio.run(
            run_post_submission_verification(
                job_id=job_id,
                submission_id=submission_id,
                verification_revision=verification_revision,
            )
        )
    except AiPriorityAdmissionDeferred as exc:
        try:
            verify_submitted_passport.apply_async(
                kwargs={
                    "job_id": job_id,
                    "submission_id": submission_id,
                    "verification_revision": verification_revision,
                },
                queue=VERIFICATION_QUEUE,
                countdown=max(1, (exc.retry_after_ms + 999) // 1_000),
            )
        except Exception as publish_exc:
            raise Reject(
                (
                    "AI admission redelivery publish failed: "
                    f"{type(publish_exc).__name__}"
                ),
                requeue=True,
            ) from publish_exc
        return
    except PostSubmissionVerificationRetryRequested as exc:
        raise self.retry(exc=exc, countdown=min(20, 5 * (self.request.retries + 1))) from exc
