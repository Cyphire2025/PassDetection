"""Passport review client: cohesive transaction and response owner."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.domain.exceptions.exceptions import (
    ConflictError,
    EntityNotFoundError,
    PassDetectionError,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.storage_cleanup import process_storage_cleanup_job
from app.infrastructure.ecr import dispatch_passport_ecr_checks
from app.presentation.api.v1.schemas.passport_schemas import (
    ClientSubmitPassportRequest,
    PassportSubmissionResponse,
)

from .dependencies import (
    _get_client_submit_passport_use_case,
)
from .submission_contact import require_verified_submission_contact
from .submission_execution import execute_client_review
from .submission_review_support import (
    _cleanup_uncommitted_promotions,
    _dispatch_committed_verification,
    logger,
)
from .submission_side_effects import stage_submission_side_effects

router = APIRouter()


@router.post(
    "/{submission_id}/client-submit",
    response_model=PassportSubmissionResponse,
    response_model_exclude={"document_follow_up", "display_name"},
    status_code=status.HTTP_200_OK,
    summary="Submit client-reviewed passport fields (Public)",
)
async def client_submit_passport(
    submission_id: uuid.UUID,
    body: ClientSubmitPassportRequest,
    background_tasks: BackgroundTasks,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    use_case: ClientSubmitPassportUseCase = Depends(_get_client_submit_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    contact_proof = await require_verified_submission_contact(
        session,
        submission_id=submission_id,
        body=body,
        upload_session_id=upload_session_id,
    )

    result: PassportSubmissionOutputDTO | None = None
    committed = False
    commit_attempted = False
    try:
        result = await execute_client_review(use_case, submission_id, body)
        effects = await stage_submission_side_effects(
            session, result=result, contact_proof=contact_proof
        )
        # Commit the DB transition before deleting superseded draft objects.
        # A failed commit therefore leaves the original draft keys intact and
        # the traveller can retry safely.
        commit_attempted = True
        await session.commit()
        committed = True
        if effects.ecr_queued:
            try:
                await dispatch_passport_ecr_checks()
            except Exception:
                # The durable row is recovered by Beat after broker recovery.
                logger.warning("passport_ecr_dispatch_deferred", submission_id=str(result.id))
        await _dispatch_committed_verification(
            effects.verification_job,
            result=result,
            session=session,
            background_tasks=background_tasks,
        )
        for cleanup_job in effects.cleanup_jobs:
            try:
                await process_storage_cleanup_job(cleanup_job.id)
            except Exception as exc:
                logger.warning(
                    "passport_draft_cleanup_deferred",
                    submission_id=str(result.id),
                    cleanup_job_id=str(cleanup_job.id),
                    object_count=cleanup_job.object_count,
                    error_type=type(exc).__name__,
                )
        return PassportSubmissionResponse.model_validate(result)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except PassDetectionError as e:
        if not committed and not commit_attempted:
            await _cleanup_uncommitted_promotions(result)
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
                if isinstance(e, ConflictError)
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=e.message,
        )
    except Exception:
        # Once commit was attempted its outcome can be ambiguous after a
        # connection loss. Deleting promoted objects could break a row that
        # PostgreSQL actually committed, so compensate only pre-commit errors.
        if not committed and not commit_attempted:
            await _cleanup_uncommitted_promotions(result)
        raise


client_submit_passport.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.submission_review"
)
