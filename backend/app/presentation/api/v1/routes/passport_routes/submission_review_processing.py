"""Passport review processing: cohesive transaction and response owner."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.get_passport_submission_use_case import (
    GetPassportSubmissionUseCase,
)
from app.application.use_cases.passports.reextract_passport_submission_use_case import (
    ReextractPassportSubmissionUseCase,
)
from app.application.use_cases.passports.retry_post_submission_verification_use_case import (
    RetryPostSubmissionVerificationUseCase,
)
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    EntityNotFoundError,
    PassDetectionError,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.verification.dispatcher import PostSubmissionVerificationDispatcher
from app.infrastructure.verification.job_repository import (
    PostSubmissionVerificationJobRepository,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportSubmissionResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .dependencies import (
    _get_get_passport_use_case,
    _get_reextract_passport_use_case,
    _get_retry_post_submission_verification_use_case,
)
from .processing_support import _dispatch_processing_job
from .response_support import _response_from_dto, _response_from_submission
from .submission_review_support import (
    logger,
)

router = APIRouter()


@router.post(
    "/{submission_id}/retry-ai-verification",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Retry AI verification after a temporary provider failure",
)
async def retry_post_submission_verification(
    submission_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    retry_use_case: RetryPostSubmissionVerificationUseCase = Depends(
        _get_retry_post_submission_verification_use_case
    ),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_confirm_passport(
            current_user,
            existing,
        )
        retry_result = await retry_use_case.execute(submission_id)
        result = retry_result.submission
        verification_job = await PostSubmissionVerificationJobRepository(session).enqueue(
            submission_id=result.id,
            verification_revision=result.post_submission_verification_revision,
        )
        await AuditLogRepository(session).record(
            action="passport_post_submission_verification_retry_requested",
            entity_type="passport_submission",
            entity_id=str(result.id),
            agency_id=result.agency_id,
            user_id=current_user.id,
            metadata={
                "group_id": str(result.group_id),
                "previous_provider_status": retry_result.previous_provider_status,
                "previous_reason_code": retry_result.previous_reason_code,
                "verification_revision": result.post_submission_verification_revision,
            },
        )

        # The submission revision and durable outbox job must be committed
        # together before any worker can claim the new revision.
        await session.commit()
        if verification_job.status == "queued":
            try:
                task_id = await PostSubmissionVerificationDispatcher().dispatch_async(
                    job_id=verification_job.id,
                    submission_id=result.id,
                    verification_revision=result.post_submission_verification_revision,
                    background_tasks=background_tasks,
                )
            except Exception as exc:
                # The recovery loop will publish the already-committed outbox
                # row. A queue outage must not lose or duplicate the request.
                logger.error(
                    "post_submission_verification_retry_dispatch_deferred",
                    job_id=str(verification_job.id),
                    error_type=type(exc).__name__,
                )
            else:
                if task_id:
                    try:
                        await PostSubmissionVerificationJobRepository(session).set_task_id(
                            verification_job.id, task_id
                        )
                        await session.commit()
                    except Exception as exc:
                        await session.rollback()
                        logger.warning(
                            "post_submission_verification_retry_task_id_persist_failed",
                            job_id=str(verification_job.id),
                            error_type=type(exc).__name__,
                        )
        return await _response_from_dto(result, session=session)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        )
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        )
    except PassDetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        )


@router.post(
    "/{submission_id}/reextract",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Rerun automatic extraction for a passport submission",
)
async def reextract_passport(
    submission_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    reextract_use_case: ReextractPassportSubmissionUseCase = Depends(
        _get_reextract_passport_use_case
    ),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_confirm_passport(current_user, existing)

        result = await reextract_use_case.execute(submission_id)
        await _dispatch_processing_job(result, session=session, background_tasks=background_tasks)
        await AuditLogRepository(session).record(
            action="passport_reextract_queued",
            entity_type="passport_submission",
            entity_id=str(result.id),
            agency_id=result.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
        )
        return await _response_from_dto(result, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.post(
    "/{submission_id}/cancel-processing",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Request cancellation of queued passport extraction",
)
async def cancel_passport_processing(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_confirm_passport(current_user, existing)

        job_repo = PassportProcessingJobRepository(session)
        job = await job_repo.latest_for_submission(submission_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Processing job was not found"
            )

        await job_repo.request_cancel(job.id)
        await AuditLogRepository(session).record(
            action="passport_processing_cancel_requested",
            entity_type="passport_submission",
            entity_id=str(submission_id),
            agency_id=existing.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={"job_id": str(job.id)},
        )
        submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)
        return await _response_from_submission(submission, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)


retry_post_submission_verification.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.submission_review"
)
reextract_passport.__module__ = "app.presentation.api.v1.routes.passport_routes.submission_review"
cancel_passport_processing.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.submission_review"
)
