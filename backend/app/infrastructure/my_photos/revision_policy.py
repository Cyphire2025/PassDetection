"""Current lease, checkpoint and terminal refresh state policy."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.infrastructure.database.my_photos_models import MyPhotoJobModel


def _refresh_claim_current(job: MyPhotoJobModel, owner: str, now: datetime) -> bool:
    expiry = job.lease_expires_at
    return bool(
        job.job_type == "refresh_searches"
        and job.status == "running"
        and job.lease_owner == owner
        and job.cancellation_requested_at is None
        and expiry is not None
        and (expiry if expiry.tzinfo is not None else expiry.replace(tzinfo=UTC)) > now
    )


def _checkpoint_uuid(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid refresh checkpoint") from exc


def _complete_job(job: MyPhotoJobModel) -> None:
    now = datetime.now(tz=UTC)
    job.status = "succeeded"
    job.attempt_count = 0
    job.processed_count = job.total_count
    job.succeeded_count = job.total_count
    job.failed_count = 0
    job.completed_at = now
    job.heartbeat_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    job.next_attempt_at = None
    job.stable_error_code = None


def _fail_job(job: MyPhotoJobModel, error_code: str) -> None:
    now = datetime.now(tz=UTC)
    job.status = "failed"
    job.stable_error_code = error_code
    job.error_detail = "Gallery refresh fan-out stopped with a stable category."
    job.completed_at = now
    job.heartbeat_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    job.next_attempt_at = None


_refresh_claim_current.__module__ = "app.infrastructure.my_photos.revision_runtime"
_checkpoint_uuid.__module__ = "app.infrastructure.my_photos.revision_runtime"
_complete_job.__module__ = "app.infrastructure.my_photos.revision_runtime"
_fail_job.__module__ = "app.infrastructure.my_photos.revision_runtime"
