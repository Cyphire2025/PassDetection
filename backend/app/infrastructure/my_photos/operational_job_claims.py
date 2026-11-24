"""Durable photo operation job claims."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from app.core.config.settings import Settings
from app.infrastructure.my_photos.operational_claim_queries import (
    gallery_allows_operations,
    locked_claim_candidate,
)
from app.infrastructure.my_photos.operational_job_contracts import (
    OperationalJobResult,
    OperationalJobType,
    OperationalWorkerContext,
    _OperationalClaim,
)
from app.infrastructure.my_photos.operational_job_lifecycle import _terminalize_job
from app.infrastructure.my_photos.operational_job_policy import _utc
from app.infrastructure.my_photos.telemetry import my_photos_metrics


async def _claim_job(
    ctx: OperationalWorkerContext,
    job_id: uuid.UUID,
    lease_owner: str,
    settings: Settings,
    *,
    allowed_job_types: frozenset[OperationalJobType] | None,
) -> _OperationalClaim | OperationalJobResult:
    async with ctx.session_factory() as session:
        rows = await locked_claim_candidate(session, job_id)
        if rows is None:
            return OperationalJobResult("noop")
        job, gallery = rows
        if job.job_type == "search_passenger":
            return OperationalJobResult("noop")
        if allowed_job_types is not None and job.job_type not in allowed_job_types:
            return OperationalJobResult("noop")
        if job.status in {"succeeded", "failed", "cancelled"}:
            return OperationalJobResult("noop")
        now = datetime.now(tz=UTC)
        if job.cancellation_requested_at is not None:
            job.status = "cancelled"
            job.completed_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            await session.commit()
            return OperationalJobResult("cancelled")
        if job.next_attempt_at is not None and _utc(job.next_attempt_at) > now:
            return OperationalJobResult(
                "retrying", max(1, math.ceil((_utc(job.next_attempt_at) - now).total_seconds()))
            )
        if (
            job.lease_owner is not None
            and job.lease_expires_at is not None
            and (_utc(job.lease_expires_at) > now)
        ):
            return OperationalJobResult(
                "lease_busy", max(1, math.ceil((_utc(job.lease_expires_at) - now).total_seconds()))
            )
        expired_lease = bool(
            job.status == "running"
            and job.lease_expires_at is not None
            and (_utc(job.lease_expires_at) <= now)
        )
        if expired_lease:
            job.attempt_count += 1
            job.stable_error_code = "WORKER_LEASE_EXPIRED"
        if job.attempt_count >= job.max_attempts:
            await _terminalize_job(session, job, "JOB_RETRY_EXHAUSTED", now=now)
            await session.commit()
            return OperationalJobResult("failed")
        if not gallery_allows_operations(gallery):
            await _terminalize_job(session, job, "JOB_SCOPE_STALE", now=now)
            await session.commit()
            return OperationalJobResult("failed")
        job.status = "running"
        if job.started_at is not None:
            redelivery_kind: Literal["index", "media", "refresh"] = (
                "index"
                if job.job_type == "index_gallery"
                else "refresh"
                if job.job_type == "refresh_searches"
                else "media"
            )
            my_photos_metrics.idempotent_redelivery(redelivery_kind)
        job.lease_owner = lease_owner
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=settings.my_photos.job_lease_seconds)
        job.next_attempt_at = None
        job.started_at = job.started_at or now
        claim = _OperationalClaim(
            job_id=job.id,
            lease_owner=lease_owner,
            job_type=cast(OperationalJobType, job.job_type),
            gallery_id=job.gallery_id,
            media_asset_id=job.media_asset_id,
            agency_id=job.agency_id,
            group_id=job.group_id,
            checkpoint_cursor=job.checkpoint_cursor,
            target_revision=job.target_revision,
            idempotency_key=job.idempotency_key,
            request_fingerprint=job.request_fingerprint,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
        )
        await session.commit()
        return claim
