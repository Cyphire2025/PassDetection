"""Public passport status: focused capability and workflow owner."""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import passport_submission_output_from_entity
from app.application.security.public_upload_capability import public_upload_is_active
from app.application.use_cases.passports.reconcile_passport_upload_use_case import (
    ReconcilePassportUploadUseCase,
)
from app.application.use_cases.passports.retry_public_passport_extraction_use_case import (
    RetryPublicPassportExtractionUseCase,
)
from app.core.security.upload_session import upload_session_matches_identifier
from app.domain.exceptions.exceptions import EntityNotFoundError, PassDetectionError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)
from app.infrastructure.processing.dispatcher import queued_job_needs_redelivery
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportSubmissionResponse,
    ReconcilePassportUploadRequest,
    ReconcilePassportUploadResponse,
)

from .dependencies import (
    _get_reconcile_passport_upload_use_case,
    _get_retry_public_extraction_use_case,
)
from .public_processing_support import dispatch_public_extraction
from .public_security import _require_public_upload_credential
from .public_upload_scope import _get_public_upload_submission
from .response_support import _response_from_dto

router = APIRouter()


@router.put(
    "/upload/{token}",
    response_model=ReconcilePassportUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Recover a durable passport upload by its attempt identifier (Public)",
)
async def reconcile_passport_upload(
    token: str,
    body: ReconcilePassportUploadRequest,
    response: Response,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    use_case: ReconcilePassportUploadUseCase = Depends(_get_reconcile_passport_upload_use_case),
) -> ReconcilePassportUploadResponse:
    if not upload_session_matches_identifier(
        upload_session_id,
        body.upload_idempotency_key,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload session identifier does not match this upload attempt.",
        )

    submission_id = await use_case.execute(
        token=token,
        upload_idempotency_key=body.upload_idempotency_key,
    )
    record_operational_event(
        OperationalEvent.UPLOAD_RESULT,
        "reconciled" if submission_id is not None else "reconcile_miss",
    )
    # Unknown keys, tokens belonging to another group, and inactive links all
    # deliberately share the same empty response. This prevents the endpoint
    # from becoming an oracle for upload-link or attempt-key enumeration.
    response.headers["Cache-Control"] = "private, no-store"
    return ReconcilePassportUploadResponse(submission_id=submission_id)


@router.get(
    "/upload/{token}/{submission_id}/status",
    response_model=PassportSubmissionResponse,
    response_model_exclude={"document_follow_up", "display_name"},
    status_code=status.HTTP_200_OK,
    summary="Poll passport extraction status for a public upload",
)
async def get_upload_passport_status(
    token: str,
    submission_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    submission = await _get_public_upload_submission(
        session,
        token=token,
        submission_id=submission_id,
        upload_session_id=upload_session_id,
    )

    # The job row is a durable outbox. If the process stopped after committing
    # it but before recording a delivery (or before an in-process background
    # task started), the first poll safely re-delivers the same revision;
    # worker claim semantics prevent duplicate extraction.
    job = await PassportProcessingJobRepository(session).latest_for_submission(submission.id)
    # Snapshot every response field before a possible dispatch commit. SQLAlchemy
    # expires loaded state on commit; reading the submission afterwards from an
    # async route can otherwise trigger an implicit synchronous refresh and
    # raise MissingGreenlet, turning an otherwise healthy status poll into 500.
    response_result = passport_submission_output_from_entity(submission, job=job)
    if job is not None and queued_job_needs_redelivery(job):
        response_result = await dispatch_public_extraction(
            response_result,
            session=session,
            background_tasks=background_tasks,
        )

    return await _response_from_dto(
        response_result,
        session=session,
        include_document_urls=False,
    )


@router.post(
    "/upload/{token}/{submission_id}/scan-again",
    response_model=PassportSubmissionResponse,
    response_model_exclude={"document_follow_up", "display_name"},
    status_code=status.HTTP_200_OK,
    summary="Retry AI passport extraction for a public upload",
)
async def scan_again_public_upload(
    token: str,
    submission_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    use_case: RetryPublicPassportExtractionUseCase = Depends(_get_retry_public_extraction_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        group = await ClientGroupRepository(session).get_by_token(token)
        if group is None or not public_upload_is_active(group):
            raise EntityNotFoundError("ClientGroup", "upload link")
        submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
        if (
            not group
            or not public_upload_is_active(group)
            or not submission
            or submission.group_id != group.id
        ):
            raise EntityNotFoundError(
                "PassportSubmission",
                submission_id,
            )
        _require_public_upload_credential(submission, upload_session_id)
        if not submission.image_s3_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No passport personal details page was collected for this submission.",
            )
        result = await use_case.execute(token=token, submission_id=submission_id)
        result = await dispatch_public_extraction(
            result,
            session=session,
            background_tasks=background_tasks,
        )
        return await _response_from_dto(
            result,
            session=session,
            include_document_urls=False,
        )
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


reconcile_passport_upload.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.public_upload"
)
get_upload_passport_status.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.public_upload"
)
scan_again_public_upload.__module__ = "app.presentation.api.v1.routes.passport_routes.public_upload"
