"""Passport public upload: focused workflow boundary."""

from __future__ import annotations

import mimetypes
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import passport_submission_output_from_entity
from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.public_upload_capability import public_upload_is_active
from app.application.use_cases.passports.reconcile_passport_upload_use_case import (
    ReconcilePassportUploadUseCase,
)
from app.application.use_cases.passports.retry_public_passport_extraction_use_case import (
    RetryPublicPassportExtractionUseCase,
)
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.core.logging.logger import get_logger
from app.core.security.upload_session import upload_session_matches_identifier
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, GroupStatus
from app.domain.exceptions.exceptions import EntityNotFoundError, PassDetectionError, StorageError
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.storage_cleanup import (
    process_storage_cleanup_job,
    stage_storage_cleanup_jobs,
)
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)
from app.infrastructure.processing.dispatcher import queued_job_needs_redelivery
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.object_streaming import private_object_streaming_response
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportSubmissionResponse,
    ReconcilePassportUploadRequest,
    ReconcilePassportUploadResponse,
)

from .dependencies import (
    _get_reconcile_passport_upload_use_case,
    _get_retry_public_extraction_use_case,
    _get_submit_passport_use_case,
)
from .processing_support import _dispatch_processing_job
from .public_security import _require_public_upload_credential, _validated_upload_file
from .public_upload_documents import validate_public_upload_documents
from .response_support import _response_from_dto

router = APIRouter()

logger = get_logger(__name__)


@router.post(
    "/upload/{token}",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a passport image using a secure token (Public)",
)
async def upload_passport(
    token: str,
    background_tasks: BackgroundTasks,
    client_name: str = Form(...),
    acquisition_mode: str = Form(..., pattern="^(camera|file)$"),
    upload_idempotency_key: str = Form(..., min_length=32, max_length=128),
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    qualifier_selection_token: str | None = Form(
        default=None,
        min_length=32,
        max_length=256,
    ),
    file: UploadFile | None = File(None, description="Passport personal details page"),
    passport_back_file: UploadFile | None = File(None, description="Passport address details page"),
    passport_photo_file: UploadFile | None = File(
        None,
        description="Optional original Visa Photo captured against a verified plain light background",
    ),
    passport_cover_file: UploadFile | None = File(None, description="Passport front cover"),
    passport_back_cover_file: UploadFile | None = File(None, description="Passport back cover"),
    visa_photo_source: str | None = Form(None, pattern="^(camera|file)$"),
    use_case: SubmitPassportUseCase = Depends(_get_submit_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    if not upload_session_matches_identifier(
        upload_session_id,
        upload_idempotency_key,
    ):
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "domain_rejected",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload session identifier does not match this upload attempt.",
        )

    # Reject revoked or unknown public capabilities before any image decoder.
    group = await ClientGroupRepository(session).get_by_token(token)
    if group is None or not public_upload_is_active(group):
        raise HTTPException(status_code=404, detail="Upload link was not found")

    document_arguments = await validate_public_upload_documents(
        group=group,
        acquisition_mode=acquisition_mode,
        visa_photo_source=visa_photo_source,
        file=file,
        passport_back_file=passport_back_file,
        passport_photo_file=passport_photo_file,
        passport_cover_file=passport_cover_file,
        passport_back_cover_file=passport_back_cover_file,
        validator=_validated_upload_file,
    )

    # 2. Execute use case
    failure_metric_recorded = False
    try:
        result = await use_case.execute(
            token=token,
            **document_arguments,
            client_name=client_name,
            acquisition_mode=acquisition_mode,
            upload_idempotency_key=upload_idempotency_key,
            qualifier_selection_token=qualifier_selection_token,
        )
        if not result.idempotent_replay:
            await propagate_mobile_passenger_change(
                session,
                agency_id=result.agency_id,
                group_id=result.group_id,
                passenger_submission_ids=[result.id],
                actor_user_id=None,
                change_kind="documents",
            )
        try:
            if result.processing_job_id:
                await _dispatch_processing_job(
                    result,
                    session=session,
                    background_tasks=background_tasks,
                )
            else:
                # A details-only draft has no processing outbox. Persist it
                # explicitly before returning the capability to the browser.
                await session.commit()
        except Exception as exc:
            await session.rollback()
            # A database commit exception is ambiguous: the server may have
            # committed before the connection failed, and this may also be an
            # idempotent replay of existing objects. Never delete durable image
            # keys here, because that could leave a committed row dangling.
            logger.error(
                "passport_upload_database_commit_failed",
                group_id=str(result.group_id),
                error_type=type(exc).__name__,
            )
            record_operational_event(
                OperationalEvent.UPLOAD_RESULT,
                "database_failed",
            )
            failure_metric_recorded = True
            raise StorageError(
                "Passport images could not be saved. Please try the upload again."
            ) from exc
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            ("idempotent_replay" if result.idempotent_replay else "success"),
        )
        return await _response_from_dto(
            result,
            session=session,
            include_document_urls=False,
        )
    except EntityNotFoundError as e:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "domain_rejected",
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except StorageError as e:
        if not failure_metric_recorded:
            record_operational_event(
                OperationalEvent.UPLOAD_RESULT,
                "storage_failed",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=e.message,
        )
    except PassDetectionError as e:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "domain_rejected",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    except Exception:
        if not failure_metric_recorded:
            record_operational_event(
                OperationalEvent.UPLOAD_RESULT,
                "unexpected_failure",
            )
        raise


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
    group = await ClientGroupRepository(session).get_by_token(token)
    if group is None or not public_upload_is_active(group):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upload link was not found"
        )

    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if not submission or submission.group_id != group.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passport submission was not found"
        )
    _require_public_upload_credential(submission, upload_session_id)

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
        await _dispatch_processing_job(
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
    status_code=status.HTTP_200_OK,
    summary="Rerun fallback MRZ extraction for a public upload",
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
        await _dispatch_processing_job(
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


@router.get(
    "/upload/{token}/{submission_id}/image",
    status_code=status.HTTP_200_OK,
    summary="Stream a public upload passport image through the API",
)
async def get_public_upload_passport_image(
    token: str,
    submission_id: uuid.UUID,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    group = await ClientGroupRepository(session).get_by_token(token)
    if group is None or not public_upload_is_active(group):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upload link was not found"
        )

    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if not submission or submission.group_id != group.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passport submission was not found"
        )
    _require_public_upload_credential(submission, upload_session_id)

    if not submission.image_s3_key:
        raise HTTPException(status_code=404, detail="The passport personal details page was not uploaded.")
    return await private_object_streaming_response(
        storage=MinioStorageRepository(),
        key=submission.image_s3_key,
        media_type=mimetypes.guess_type(submission.image_s3_key)[0] or "image/jpeg",
        content_disposition='inline; filename="passport.jpg"',
        range_header=range_header,
    )


@router.get(
    "/upload/{token}/{submission_id}/image/{document_type}",
    status_code=status.HTTP_200_OK,
    summary="Stream one stored public passport document through the API",
)
async def get_public_upload_passport_document(
    token: str,
    submission_id: uuid.UUID,
    document_type: str,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    group = await ClientGroupRepository(session).get_by_token(token)
    if group is None or not public_upload_is_active(group):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upload link was not found"
        )

    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if not submission or submission.group_id != group.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport submission was not found",
        )
    _require_public_upload_credential(submission, upload_session_id)

    keys = {
        "front": submission.image_s3_key,
        "back": submission.passport_back_s3_key,
        "photo": submission.passport_photo_s3_key,
        "cover": submission.passport_cover_s3_key,
        "back_cover": submission.passport_back_cover_s3_key,
    }
    if document_type not in keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose front, back, cover, back_cover, or photo.",
        )
    key = keys[document_type]
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested passport document was not uploaded.",
        )
    return await private_object_streaming_response(
        storage=MinioStorageRepository(),
        key=key,
        media_type=mimetypes.guess_type(key)[0] or "image/jpeg",
        content_disposition=f'inline; filename="passport-{document_type}"',
        range_header=range_header,
    )


@router.delete(
    "/upload/{token}/{submission_id}",
    status_code=status.HTTP_200_OK,
    summary="Discard an unsubmitted public passport draft",
)
async def discard_public_upload(
    token: str,
    submission_id: uuid.UUID,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    group = await ClientGroupRepository(session).get_by_token(token)
    if group is None or not public_upload_is_active(group):
        raise HTTPException(status_code=404, detail="Passport draft was not found")
    locked_group = None
    if group is not None and public_upload_is_active(group):
        locked_group = await session.scalar(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == group.id,
                ClientGroupModel.agency_id == group.agency_id,
                ClientGroupModel.status == GroupStatus.ACTIVE.value,
                ClientGroupModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
    submission_repo = PassportSubmissionRepository(session)
    submission = await submission_repo.get_by_id_for_update(submission_id)
    if (
        group is None
        or locked_group is None
        or submission is None
        or submission.group_id != group.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passport draft was not found"
        )
    try:
        _require_public_upload_credential(submission, upload_session_id)
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport draft was not found",
        ) from exc
    if submission.status.value in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Submitted passports cannot be discarded"
        )
    if locked_group.passport_legal_hold:
        await AuditLogRepository(session).record(
            action="public_passport_draft_discard_blocked",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=locked_group.agency_id,
            result="blocked",
            metadata={"reason_code": "PASSPORT_LEGAL_HOLD_ACTIVE"},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PASSPORT_LEGAL_HOLD_ACTIVE",
                "message": "This passport draft is retained under a legal hold.",
            },
        )

    keys = [
        key
        for key in (
            submission.image_s3_key,
            submission.thumbnail_s3_key,
            submission.passport_photo_s3_key,
            submission.passport_back_s3_key,
            submission.passport_cover_s3_key,
            submission.passport_back_cover_s3_key,
        )
        if key
    ]
    cleanup_jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=locked_group.agency_id,
        source="passport_submission_delete",
        context_id=f"public-draft:{submission.id}",
        storage_keys=keys,
    )
    await submission_repo.delete(submission.id)
    await AuditLogRepository(session).record(
        action="public_passport_draft_discarded",
        entity_type="passport_submission",
        entity_id=str(submission.id),
        agency_id=locked_group.agency_id,
        metadata={
            "storage_cleanup_job_count": len(cleanup_jobs),
            "storage_objects_scheduled_for_cleanup": len(keys),
        },
    )
    # The encrypted cleanup tombstone and authoritative row deletion share
    # one commit. A failed/ambiguous commit therefore never triggers object
    # deletion, and a worker can safely retry after storage failures.
    await session.commit()
    for cleanup_job in cleanup_jobs:
        try:
            await process_storage_cleanup_job(cleanup_job.id)
        except Exception as exc:
            logger.warning(
                "discarded_passport_object_cleanup_deferred",
                submission_id=str(submission.id),
                cleanup_job_id=str(cleanup_job.id),
                object_count=cleanup_job.object_count,
                error_type=type(exc).__name__,
            )
    record_operational_event(
        OperationalEvent.PUBLIC_FLOW,
        "upload_abandoned",
    )
    return {"discarded": True}
