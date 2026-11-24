"""Passport review read: cohesive transaction and response owner."""

from __future__ import annotations

import uuid
from dataclasses import replace

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.get_passport_submission_use_case import (
    GetPassportSubmissionUseCase,
)
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    EntityNotFoundError,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.processing.dispatcher import queued_job_needs_redelivery
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportSubmissionResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

from .dependencies import (
    _get_get_passport_use_case,
)
from .processing_support import _dispatch_processing_job
from .response_support import _response_from_dto

router = APIRouter()


@router.get(
    "/{submission_id}",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a passport submission by id",
)
async def get_passport(
    submission_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        result = await use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_view_passport(current_user, result)
        await record_sensitive_read(
            session,
            user=current_user,
            kind="detail",
            agency_id=result.agency_id,
            entity_id=result.id,
        )

        job = await PassportProcessingJobRepository(session).latest_for_submission(result.id)
        if job is not None and queued_job_needs_redelivery(job):
            await _dispatch_processing_job(
                replace(
                    result,
                    processing_job_id=job.id,
                    processing_job_status=job.status.value,
                    processing_progress=job.progress,
                    processing_stage=job.current_stage,
                ),
                session=session,
                background_tasks=background_tasks,
            )
        return await _response_from_dto(result, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)


get_passport.__module__ = "app.presentation.api.v1.routes.passport_routes.submission_review"
