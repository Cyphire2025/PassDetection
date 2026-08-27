"""Celery entry point for durable passenger face searches."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast

from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.my_photos import (
    MY_PHOTOS_CONTROL_QUEUE,
    MY_PHOTOS_INDEX_QUEUE,
    MY_PHOTOS_INDEX_TASK,
    MY_PHOTOS_MEDIA_QUEUE,
    MY_PHOTOS_MEDIA_TASK,
    MY_PHOTOS_RECOVERY_TASK,
    MY_PHOTOS_SEARCH_QUEUE,
    MY_PHOTOS_SEARCH_TASK,
)
from app.infrastructure.my_photos.operational_runtime import execute_operational_job
from app.infrastructure.my_photos.recovery_runtime import (
    DurableDispatch,
    ProviderDeletionBatchResult,
    execute_provider_deletion_batch,
    recoverable_dispatches,
)
from app.infrastructure.my_photos.worker_runtime import execute_search_job
from app.infrastructure.processing.celery_app import celery_app


@celery_app.task(
    bind=True,
    name=MY_PHOTOS_SEARCH_TASK,
    queue=MY_PHOTOS_SEARCH_QUEUE,
    max_retries=20,
)  # type: ignore[untyped-decorator]
def search_passenger_photos(self: Any, search_run_id: str) -> str:
    try:
        parsed_id = uuid.UUID(search_run_id)
    except (TypeError, ValueError):
        return "invalid_task_payload"
    try:
        result = celery_async_runtime.run(execute_search_job(parsed_id))
    except Exception:
        # A database outage or process interruption before durable retry state
        # is written must still schedule bounded broker redelivery. Never attach
        # the raw exception because it may contain provider details.
        raise self.retry(countdown=1) from None
    if result.state in {"retrying", "lease_busy", "lease_lost"}:
        raise self.retry(countdown=result.retry_after_seconds or 1)
    return cast(str, result.state)


def _operational_task(
    task: Any,
    job_id: str,
    *,
    allowed_job_types: frozenset[Any],
) -> str:
    try:
        parsed_id = uuid.UUID(job_id)
    except (TypeError, ValueError):
        return "invalid_task_payload"
    try:
        result = celery_async_runtime.run(
            execute_operational_job(parsed_id, allowed_job_types=allowed_job_types)
        )
        for search_run_id in result.search_run_ids:
            celery_app.send_task(
                MY_PHOTOS_SEARCH_TASK,
                args=[str(search_run_id)],
                queue=MY_PHOTOS_SEARCH_QUEUE,
            )
        for followup_job_id in result.followup_job_ids:
            celery_app.send_task(
                MY_PHOTOS_INDEX_TASK,
                args=[str(followup_job_id)],
                queue=MY_PHOTOS_INDEX_QUEUE,
            )
    except Exception:
        raise task.retry(countdown=1) from None
    if result.state in {"retrying", "lease_busy", "lease_lost"}:
        raise task.retry(countdown=result.retry_after_seconds or 1)
    return cast(str, result.state)


@celery_app.task(
    bind=True,
    name=MY_PHOTOS_INDEX_TASK,
    queue=MY_PHOTOS_INDEX_QUEUE,
    max_retries=20,
    soft_time_limit=65,
    time_limit=75,
)  # type: ignore[untyped-decorator]
def process_index_job(self: Any, job_id: str) -> str:
    return _operational_task(
        self,
        job_id,
        allowed_job_types=frozenset({"index_gallery", "refresh_searches"}),
    )


@celery_app.task(
    bind=True,
    name=MY_PHOTOS_MEDIA_TASK,
    queue=MY_PHOTOS_MEDIA_QUEUE,
    max_retries=20,
    soft_time_limit=65,
    time_limit=75,
)  # type: ignore[untyped-decorator]
def process_media_job(self: Any, job_id: str) -> str:
    return _operational_task(
        self,
        job_id,
        allowed_job_types=frozenset({"generate_variants", "prepare_media"}),
    )


async def _recover_cycle() -> tuple[tuple[DurableDispatch, ...], ProviderDeletionBatchResult]:
    dispatches, deletion = await asyncio.gather(
        recoverable_dispatches(),
        execute_provider_deletion_batch(),
    )
    return dispatches, deletion


@celery_app.task(
    name=MY_PHOTOS_RECOVERY_TASK,
    queue=MY_PHOTOS_CONTROL_QUEUE,
    soft_time_limit=210,
    time_limit=240,
)  # type: ignore[untyped-decorator]
def recover_durable_jobs() -> str:
    dispatches, deletion = celery_async_runtime.run(_recover_cycle())
    for dispatch in dispatches:
        if dispatch.kind == "search" and dispatch.search_run_id is not None:
            celery_app.send_task(
                MY_PHOTOS_SEARCH_TASK,
                args=[str(dispatch.search_run_id)],
                queue=MY_PHOTOS_SEARCH_QUEUE,
            )
        elif dispatch.kind == "index":
            celery_app.send_task(
                MY_PHOTOS_INDEX_TASK,
                args=[str(dispatch.job_id)],
                queue=MY_PHOTOS_INDEX_QUEUE,
            )
        elif dispatch.kind == "media":
            celery_app.send_task(
                MY_PHOTOS_MEDIA_TASK,
                args=[str(dispatch.job_id)],
                queue=MY_PHOTOS_MEDIA_QUEUE,
            )
    return (
        f"dispatched={len(dispatches)};deletions={deletion.completed};"
        f"retrying={deletion.retrying};failed={deletion.terminal_failed}"
    )


__all__ = [
    "celery_async_runtime",
    "process_index_job",
    "process_media_job",
    "recover_durable_jobs",
    "search_passenger_photos",
]
