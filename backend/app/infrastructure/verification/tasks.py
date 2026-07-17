"""Celery task for durable post-submit passport verification."""

from __future__ import annotations

import asyncio

from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.verification.runtime import (
    PostSubmissionVerificationRetryRequested,
    run_post_submission_verification,
)


@celery_app.task(
    bind=True,
    name="passport.verify_submitted",
    queue="passport_ocr",
    max_retries=3,
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
    except PostSubmissionVerificationRetryRequested as exc:
        raise self.retry(exc=exc, countdown=min(20, 5 * (self.request.retries + 1))) from exc
