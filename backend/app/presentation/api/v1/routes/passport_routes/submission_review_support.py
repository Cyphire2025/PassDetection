"""Passport review support: cohesive transaction and response owner."""

from __future__ import annotations

from fastapi import BackgroundTasks, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import (
    StaffApprovalStaleError,
    StaffApprovalUnavailableError,
    StorageError,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.verification.dispatcher import PostSubmissionVerificationDispatcher
from app.infrastructure.verification.job_repository import (
    PostSubmissionVerificationJob,
    PostSubmissionVerificationJobRepository,
)

logger = get_logger("app.presentation.api.v1.routes.passport_routes.submission_review")


async def _cleanup_uncommitted_promotions(
    result: PassportSubmissionOutputDTO | None,
) -> None:
    if not result or not result.promoted_storage_keys:
        return
    try:
        await MinioStorageRepository().delete_files(list(result.promoted_storage_keys))
    except StorageError as exc:
        logger.warning(
            "passport_promotion_rollback_cleanup_failed",
            submission_id=str(result.id),
            object_count=len(result.promoted_storage_keys),
            error_type=type(exc).__name__,
        )


async def _dispatch_committed_verification(
    job: PostSubmissionVerificationJob | None,
    *,
    result: PassportSubmissionOutputDTO,
    session: AsyncSession,
    background_tasks: BackgroundTasks,
) -> None:
    """Deliver an existing outbox job after submission state has committed."""
    if job is None or job.status != "queued":
        return
    task_id = await PostSubmissionVerificationDispatcher().dispatch_async(
        job_id=job.id,
        submission_id=result.id,
        verification_revision=result.post_submission_verification_revision,
        background_tasks=background_tasks,
    )
    if not task_id:
        return
    try:
        await PostSubmissionVerificationJobRepository(session).set_task_id(job.id, task_id)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.warning(
            "post_submission_verification_task_id_persist_failed",
            job_id=str(job.id),
            error_type=type(exc).__name__,
        )


def _staff_approval_conflict_response(
    error: StaffApprovalStaleError | StaffApprovalUnavailableError,
) -> JSONResponse:
    details: dict[str, object] = {}
    if isinstance(error, StaffApprovalStaleError):
        details["current_revision"] = error.current_revision
    else:
        details["current_status"] = error.current_status
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": details,
            }
        },
        headers={"Cache-Control": "no-store"},
    )


async def _schedule_review_history(
    session: AsyncSession,
    *,
    result: PassportSubmissionOutputDTO,
    trigger: str,
) -> None:
    """Schedule immutable history and acknowledge retained trip evidence together."""
    from app.application.travellers.history_schedule import schedule_submission_history

    await schedule_submission_history(
        session,
        agency_id=result.agency_id,
        group_id=result.group_id,
        source_submission_id=result.id,
        expected_extraction_revision=result.extraction_revision,
        trigger=trigger,
    )
    from app.application.travellers.snapshot_access import (
        has_retained_document,
        sync_accepted_participations,
    )

    if has_retained_document(result):
        await sync_accepted_participations(
            session,
            agency_id=result.agency_id,
            group_id=result.group_id,
            submission_ids=[result.id],
        )


_cleanup_uncommitted_promotions.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.submission_review"
)
_dispatch_committed_verification.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.submission_review"
)
_staff_approval_conflict_response.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.submission_review"
)
_schedule_review_history.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.submission_review"
)
