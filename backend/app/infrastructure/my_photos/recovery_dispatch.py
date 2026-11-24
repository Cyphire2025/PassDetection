"""Bounded durable dispatch selection and canonical cancellation locking."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, or_, select

from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import MyPhotoJobModel, MyPhotoSearchRunModel
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.recovery_contracts import DurableDispatch, RecoveryContext
from app.infrastructure.my_photos.telemetry import my_photos_metrics


async def _due_dispatches(
    ctx: RecoveryContext, resolved: Settings, due_at: datetime
) -> tuple[DurableDispatch, ...]:
    async with ctx.sessions() as session:
        depth_rows = list(
            (
                await session.execute(
                    select(MyPhotoJobModel.job_type, func.count(MyPhotoJobModel.id))
                    .where(MyPhotoJobModel.status.in_(("queued", "running", "retrying")))
                    .group_by(MyPhotoJobModel.job_type)
                )
            ).tuples()
        )
        jobs = list(
            (
                await session.execute(
                    select(MyPhotoJobModel)
                    .where(
                        or_(
                            and_(
                                MyPhotoJobModel.status.in_(("queued", "retrying")),
                                or_(
                                    MyPhotoJobModel.next_attempt_at.is_(None),
                                    MyPhotoJobModel.next_attempt_at <= due_at,
                                ),
                            ),
                            and_(
                                MyPhotoJobModel.status == "running",
                                MyPhotoJobModel.lease_expires_at.is_not(None),
                                MyPhotoJobModel.lease_expires_at <= due_at,
                            ),
                        )
                    )
                    .order_by(MyPhotoJobModel.created_at, MyPhotoJobModel.id)
                    .limit(resolved.my_photos.recovery_batch_size)
                )
            ).scalars()
        )
    depths = {str(job_type): int(count) for job_type, count in depth_rows}
    my_photos_metrics.queue_depth("search", depths.get("search_passenger", 0))
    my_photos_metrics.queue_depth(
        "index", depths.get("index_gallery", 0) + depths.get("refresh_searches", 0)
    )
    my_photos_metrics.queue_depth(
        "media", depths.get("generate_variants", 0) + depths.get("prepare_media", 0)
    )
    dispatches: list[DurableDispatch] = []
    for job in jobs:
        if job.job_type == "search_passenger" and job.search_run_id is not None:
            dispatches.append(DurableDispatch(job.id, "search", job.search_run_id))
        elif job.job_type in {"index_gallery", "refresh_searches"}:
            dispatches.append(DurableDispatch(job.id, "index"))
        elif job.job_type in {"generate_variants", "prepare_media"}:
            dispatches.append(DurableDispatch(job.id, "media"))
    return tuple(dispatches)


async def _terminalize_requested_cancellations(
    ctx: RecoveryContext, settings: Settings, now: datetime
) -> int:
    """Finalize a bounded cancellation batch, including expired worker leases."""

    async with ctx.sessions() as session:
        # Lock search rows before their jobs, matching search result publication.
        # SKIP LOCKED keeps watchdogs nonblocking; both reads retain the same
        # batch limit and recheck cancellation/status before mutation.
        searches = {
            row.id: row
            for row in (
                await session.execute(
                    select(MyPhotoSearchRunModel)
                    .join(
                        MyPhotoJobModel,
                        and_(
                            MyPhotoJobModel.search_run_id == MyPhotoSearchRunModel.id,
                            MyPhotoJobModel.agency_id == MyPhotoSearchRunModel.agency_id,
                            MyPhotoJobModel.group_id == MyPhotoSearchRunModel.group_id,
                        ),
                    )
                    .where(
                        MyPhotoJobModel.status.in_(("queued", "running", "retrying")),
                        MyPhotoJobModel.cancellation_requested_at.is_not(None),
                    )
                    .order_by(MyPhotoJobModel.cancellation_requested_at, MyPhotoJobModel.id)
                    .with_for_update(of=MyPhotoSearchRunModel, skip_locked=True)
                    .limit(settings.my_photos.recovery_batch_size)
                )
            ).scalars()
        }
        jobs = list(
            (
                await session.execute(
                    select(MyPhotoJobModel)
                    .where(
                        MyPhotoJobModel.status.in_(("queued", "running", "retrying")),
                        MyPhotoJobModel.cancellation_requested_at.is_not(None),
                        or_(
                            MyPhotoJobModel.search_run_id.is_(None),
                            MyPhotoJobModel.search_run_id.in_(tuple(searches)),
                        ),
                    )
                    .order_by(
                        MyPhotoJobModel.cancellation_requested_at,
                        MyPhotoJobModel.id,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(settings.my_photos.recovery_batch_size)
                )
            ).scalars()
        )
        if not jobs:
            return 0
        for job in jobs:
            job.status = "cancelled"
            job.completed_at = now
            job.heartbeat_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            job.next_attempt_at = None
            job.stable_error_code = "CANCELLED_BY_REQUEST"
            if job.search_run_id is not None:
                search = searches.get(job.search_run_id)
                if search is not None and search.status not in {"complete", "failed", "cancelled"}:
                    search.status = "cancelled"
                    search.completed_at = now
                    search.heartbeat_at = now
                    search.lease_owner = None
                    search.lease_expires_at = None
                    search.stable_error_code = "CANCELLED_BY_REQUEST"
            await record_my_photos_audit(
                session,
                action="my_photos_job_cancelled",
                agency_id=job.agency_id,
                group_id=job.group_id,
                outcome=job.job_type,
            )
            my_photos_metrics.job("cancelled")
        await session.commit()
        return len(jobs)
