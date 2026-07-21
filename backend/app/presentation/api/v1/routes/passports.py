"""
Passport Routes — /api/v1/passports
===================================
"""

from __future__ import annotations

import asyncio
import io
import mimetypes
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.application.use_cases.passports.confirm_passport_submission_use_case import (
    ConfirmPassportSubmissionUseCase,
)
from app.application.use_cases.passports.get_passport_submission_use_case import (
    GetPassportSubmissionUseCase,
)
from app.application.use_cases.passports.list_passport_group_summaries_use_case import (
    ListPassportGroupSummariesUseCase,
)
from app.application.use_cases.passports.list_passport_submissions_by_group_use_case import (
    ListPassportSubmissionsByGroupUseCase,
)
from app.application.use_cases.passports.list_passport_submissions_use_case import (
    ListPassportSubmissionsUseCase,
)
from app.application.use_cases.passports.reconcile_passport_upload_use_case import (
    ReconcilePassportUploadUseCase,
)
from app.application.use_cases.passports.reextract_passport_submission_use_case import (
    ReextractPassportSubmissionUseCase,
)
from app.application.use_cases.passports.retry_post_submission_verification_use_case import (
    RetryPostSubmissionVerificationUseCase,
)
from app.application.use_cases.passports.retry_public_passport_extraction_use_case import (
    RetryPublicPassportExtractionUseCase,
)
from app.application.use_cases.passports.staff_approve_passport_use_case import (
    StaffApprovalResult,
    StaffApprovePassportUseCase,
)
from app.application.use_cases.passports.submission_view import (
    build_submission_view,
)
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.core.logging.logger import get_logger
from app.core.security.upload_session import upload_session_matches_identifier
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    StaffApprovalOutcome,
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    EntityNotFoundError,
    PassDetectionError,
    StaffApprovalStaleError,
    StaffApprovalUnavailableError,
    StorageError,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    NotificationModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.passport_excel_exporter import PassportExcelExporter
from app.infrastructure.export.passport_image_zip_exporter import (
    MissingPassportImagesError,
    PassportImageExportLimitError,
    PassportImageZipExporter,
    safe_download_filename,
)
from app.infrastructure.imports.passport_document_importer import (
    PassportDocumentFile,
    PassportDocumentImporter,
    RejectedPassportDocument,
)
from app.infrastructure.imports.passport_excel_importer import PassportExcelImporter
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)
from app.infrastructure.processing.dispatcher import (
    PassportProcessingDispatcher,
    queued_job_needs_redelivery,
)
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.qr.approved_passenger_qr_issuer import (
    ensure_approved_passenger_qr,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.notification_repository import NotificationRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.qualifier_selection_repository import (
    QualifierSelectionRepository,
)
from app.infrastructure.security.upload_validator import UploadValidator
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.storage.passport_object_keys import passport_storage_keys
from app.infrastructure.verification.dispatcher import (
    PostSubmissionVerificationDispatcher,
)
from app.infrastructure.verification.job_repository import (
    PostSubmissionVerificationJobRepository,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkDeletePassportSubmissionsRequest,
    BulkDeletePassportSubmissionsResponse,
    ClientSubmitPassportRequest,
    ConfirmPassportSubmissionRequest,
    ExportSelectedGroupsRequest,
    ExportSelectedPassportsRequest,
    ImportPassportGroupResponse,
    PassportDocumentImportItem,
    PassportDocumentImportPreviewResponse,
    PassportDocumentImportSaveResponse,
    PassportExpiryAlertResponse,
    PassportGroupSummaryResponse,
    PassportSubmissionResponse,
    PassportSubmissionsViewResponse,
    PassportSubmissionViewItemResponse,
    ReconcilePassportUploadRequest,
    ReconcilePassportUploadResponse,
    StaffApprovePassportRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
logger = get_logger(__name__)


def _owner_scope_for(user: User) -> uuid.UUID | None:
    return user.id if user.role == UserRole.AGENCY_STAFF else None


def _stream_binary_file(file_object, *, chunk_size: int = 1024 * 1024):  # type: ignore[no-untyped-def]
    try:
        while chunk := file_object.read(chunk_size):
            yield chunk
    finally:
        file_object.close()


def _submitted_statuses() -> tuple[str, ...]:
    return OFFICE_VISIBLE_PASSPORT_STATUS_VALUES


def _require_public_upload_credential(
    submission: object,
    upload_session_id: str,
) -> None:
    """Require a per-upload capability that is independent of the public UUID."""

    expected = getattr(submission, "upload_idempotency_key", None)
    if not isinstance(expected, str) or not upload_session_matches_identifier(
        upload_session_id,
        expected,
    ):
        # Use the same response as an unknown submission so this check does
        # not become a capability-validation oracle.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport submission was not found",
        )


async def _safe_presigned_url(
    storage: MinioStorageRepository,
    key: str | None,
) -> str | None:
    if not key:
        return None
    try:
        return await storage.get_presigned_url(key)
    except StorageError as exc:
        logger.warning(
            "passport_presigned_url_unavailable",
            error_type=type(exc).__name__,
        )
        return None


async def _cleanup_uncommitted_promotions(
    result: PassportSubmissionOutputDTO | None,
) -> None:
    if not result or not result.promoted_storage_keys:
        return
    try:
        await MinioStorageRepository().delete_files(
            list(result.promoted_storage_keys)
        )
    except StorageError as exc:
        logger.warning(
            "passport_promotion_rollback_cleanup_failed",
            submission_id=str(result.id),
            object_count=len(result.promoted_storage_keys),
            error_type=type(exc).__name__,
        )


def _apply_manager_visibility(stmt, current_user: User):  # type: ignore[no-untyped-def]
    return AuthorizationPolicy.apply_passport_visibility_scope(stmt, current_user)


async def _response_from_dto(
    result: PassportSubmissionOutputDTO,
    *,
    session: AsyncSession,
    include_document_urls: bool = True,
) -> PassportSubmissionResponse:
    storage = MinioStorageRepository()
    payload = {
        **result.__dict__,
        "image_url": (
            await _safe_presigned_url(storage, result.image_s3_key)
            if include_document_urls
            else None
        ),
        "passport_photo_url": (
            await _safe_presigned_url(storage, result.passport_photo_s3_key)
            if include_document_urls
            else None
        ),
        "passport_back_url": (
            await _safe_presigned_url(storage, result.passport_back_s3_key)
            if include_document_urls
            else None
        ),
        "qr_status": await _passport_qr_status(session, result.id),
    }
    if not payload.get("processing_job_id"):
        job = await PassportProcessingJobRepository(session).latest_for_submission(result.id)
        if job:
            payload.update(
                {
                    "processing_job_id": job.id,
                    "processing_job_status": job.status.value,
                    "processing_progress": job.progress,
                    "processing_stage": job.current_stage,
                }
            )
    return PassportSubmissionResponse.model_validate(payload)


async def _response_from_submission(
    submission,
    *,
    session: AsyncSession,
) -> PassportSubmissionResponse:  # type: ignore[no-untyped-def]
    storage = MinioStorageRepository()
    payload = {
        **submission.__dict__,
        "status": submission.status.value,
        "image_url": await _safe_presigned_url(storage, submission.image_s3_key),
        "passport_photo_url": await _safe_presigned_url(storage, submission.passport_photo_s3_key),
        "passport_back_url": await _safe_presigned_url(storage, submission.passport_back_s3_key),
        "qr_status": await _passport_qr_status(session, submission.id),
    }
    job = await PassportProcessingJobRepository(session).latest_for_submission(submission.id)
    if job:
        payload.update(
            {
                "processing_job_id": job.id,
                "processing_job_status": job.status.value,
                "processing_progress": job.progress,
                "processing_stage": job.current_stage,
            }
        )
    return PassportSubmissionResponse.model_validate(payload)


async def _passport_qr_status(session: AsyncSession, passenger_id: uuid.UUID) -> dict[str, object | None]:
    result = await session.execute(
        select(PassengerQRTokenModel)
        .where(PassengerQRTokenModel.passenger_id == passenger_id)
        .order_by(PassengerQRTokenModel.token_version.desc(), PassengerQRTokenModel.created_at.desc())
        .limit(1)
    )
    token = result.scalar_one_or_none()
    if token is None:
        return {"status": "not_generated"}
    now = datetime.now(tz=UTC)
    if token.revoked_at is not None:
        token_status = "revoked"
    elif token.expires_at <= now:
        token_status = "expired"
    else:
        token_status = "active" if token.is_active else "inactive"
    return {
        "status": token_status,
        "token_version": token.token_version,
        "created_at": token.created_at,
        "expires_at": token.expires_at,
        "revoked_at": token.revoked_at,
    }


async def _ensure_submission_qr(
    session: AsyncSession,
    submission_id: uuid.UUID,
    created_by_user_id: uuid.UUID | None = None,
) -> None:
    await ensure_approved_passenger_qr(
        session,
        submission_id,
        created_by_user_id=created_by_user_id,
    )


def _group_export_details(
    group,
) -> dict[str, str | bool | None]:  # type: ignore[no-untyped-def]
    return {
        "name": group.name,
        "destination": group.destination,
        "travel_date": group.travel_date.isoformat() if group.travel_date else None,
        "return_date": group.return_date.isoformat() if group.return_date else None,
        "package_name": group.package_name,
        "nearest_international_airport_enabled": (
            group.nearest_international_airport_enabled
        ),
        "ask_nearest_domestic_airport": group.ask_nearest_domestic_airport,
        "base_city_enabled": group.base_city_enabled,
        "staff_code_enabled": group.staff_code_enabled,
        "meal_preference_enabled": group.meal_preference_enabled,
        "relation_with_qualifier_enabled": (
            group.relation_with_qualifier_enabled
        ),
    }


async def _export_group_details(
    session: AsyncSession,
    group_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, str | bool | None]]:
    if not group_ids:
        return {}
    result = await session.execute(select(ClientGroupModel).where(ClientGroupModel.id.in_(set(group_ids))))
    return {group.id: _group_export_details(group) for group in result.scalars().all()}


async def _dispatch_processing_job(
    result: PassportSubmissionOutputDTO,
    *,
    session: AsyncSession,
    background_tasks: BackgroundTasks,
) -> None:
    if not result.processing_job_id:
        return

    # The worker uses a separate database session, so commit the queued rows
    # before dispatching to avoid a race with the worker reading the job.
    await session.commit()
    try:
        task_id = PassportProcessingDispatcher().dispatch(
            job_id=result.processing_job_id,
            submission_id=result.id,
            background_tasks=background_tasks,
        )
    except Exception as exc:
        # The submission and image keys are durable at this point. Dispatch is
        # best effort and must never turn persistence success into an upload
        # failure (or trigger compensation that deletes committed objects).
        logger.error(
            "passport_processing_dispatch_failed_after_persistence",
            job_id=str(result.processing_job_id),
            error_type=type(exc).__name__,
        )
        return
    try:
        await PassportProcessingJobRepository(session).set_task_id(
            result.processing_job_id,
            task_id or "local-background",
        )
        await session.commit()
    except Exception as exc:
        # The submission and job were already committed before dispatch.
        # Losing optional queue metadata must not turn a successful upload
        # into a reported upload failure.
        await session.rollback()
        logger.warning(
            "passport_processing_task_id_not_recorded",
            job_id=str(result.processing_job_id),
            error_type=type(exc).__name__,
        )


async def _validated_upload_file(file: UploadFile, *, label: str):
    try:
        content = await file.read()
    except Exception:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "read_error",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read {label} file content",
        )
    try:
        return await asyncio.to_thread(
            UploadValidator().validate,
            content=content,
            filename=file.filename,
            declared_content_type=file.content_type,
        )
    except PassDetectionError as exc:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "validation_failed",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)


def _get_submit_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> SubmitPassportUseCase:
    return SubmitPassportUseCase(
        client_group_repo=ClientGroupRepository(session),
        passport_repo=PassportSubmissionRepository(session),
        storage_repo=MinioStorageRepository(),
        processing_job_repo=PassportProcessingJobRepository(session),
        qualifier_selection_repo=QualifierSelectionRepository(session),
    )


def _get_reconcile_passport_upload_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ReconcilePassportUploadUseCase:
    return ReconcilePassportUploadUseCase(
        client_group_repo=ClientGroupRepository(session),
        passport_repo=PassportSubmissionRepository(session),
    )


def _get_list_passports_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ListPassportSubmissionsUseCase:
    return ListPassportSubmissionsUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_list_passport_groups_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ListPassportGroupSummariesUseCase:
    return ListPassportGroupSummariesUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_list_passports_by_group_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ListPassportSubmissionsByGroupUseCase:
    return ListPassportSubmissionsByGroupUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_get_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> GetPassportSubmissionUseCase:
    return GetPassportSubmissionUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_confirm_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ConfirmPassportSubmissionUseCase:
    return ConfirmPassportSubmissionUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_client_submit_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ClientSubmitPassportUseCase:
    return ClientSubmitPassportUseCase(
        passport_repo=PassportSubmissionRepository(session),
        client_group_repo=ClientGroupRepository(session),
        storage_repo=MinioStorageRepository(),
    )


def _get_reextract_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ReextractPassportSubmissionUseCase:
    return ReextractPassportSubmissionUseCase(
        passport_repo=PassportSubmissionRepository(session),
        processing_job_repo=PassportProcessingJobRepository(session),
    )


def _get_retry_public_extraction_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RetryPublicPassportExtractionUseCase:
    return RetryPublicPassportExtractionUseCase(
        passport_repo=PassportSubmissionRepository(session),
        client_group_repo=ClientGroupRepository(session),
        processing_job_repo=PassportProcessingJobRepository(session),
    )


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
    file: UploadFile = File(...),
    passport_back_file: UploadFile = File(..., description="Required original passport back image"),
    passport_photo_file: UploadFile | None = File(
        None,
        description="Optional original Visa Photo captured against a verified plain light background",
    ),
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

    # 1. Read and validate file content using magic bytes + actual decoder.
    validated = await _validated_upload_file(file, label="passport front")
    validated_photo = (
        await _validated_upload_file(passport_photo_file, label="Visa Photo")
        if passport_photo_file
        else None
    )
    validated_back = await _validated_upload_file(passport_back_file, label="passport back")

    # 2. Execute use case
    failure_metric_recorded = False
    try:
        result = await use_case.execute(
            token=token,
            file_content=validated.content,
            content_type=validated.content_type,
            filename=validated.filename,
            client_name=client_name,
            passport_photo=(validated_photo.content, validated_photo.content_type, validated_photo.filename) if validated_photo else None,
            passport_back=(validated_back.content, validated_back.content_type, validated_back.filename),
            acquisition_mode=acquisition_mode,
            upload_idempotency_key=upload_idempotency_key,
            qualifier_selection_token=qualifier_selection_token,
        )
        try:
            await _dispatch_processing_job(
                result,
                session=session,
                background_tasks=background_tasks,
            )
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
            (
                "idempotent_replay"
                if result.idempotent_replay
                else "success"
            ),
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
    use_case: ReconcilePassportUploadUseCase = Depends(
        _get_reconcile_passport_upload_use_case
    ),
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
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload link was not found")

    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if not submission or submission.group_id != group.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passport submission was not found")
    _require_public_upload_credential(submission, upload_session_id)

    # The job row is a durable outbox. If the process stopped after committing
    # it but before recording a delivery (or before an in-process background
    # task started), the first poll safely re-delivers the same revision;
    # worker claim semantics prevent duplicate extraction.
    job = await PassportProcessingJobRepository(session).latest_for_submission(
        submission.id
    )
    # Snapshot every response field before a possible dispatch commit. SQLAlchemy
    # expires loaded state on commit; reading the submission afterwards from an
    # async route can otherwise trigger an implicit synchronous refresh and
    # raise MissingGreenlet, turning an otherwise healthy status poll into 500.
    response_result = passport_submission_output_from_entity(submission, job=job)
    if (
        job is not None
        and queued_job_needs_redelivery(job)
    ):
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
        submission = await PassportSubmissionRepository(session).get_by_id(
            submission_id
        )
        if (
            not group
            or not submission
            or submission.group_id != group.id
        ):
            raise EntityNotFoundError(
                "PassportSubmission",
                submission_id,
            )
        _require_public_upload_credential(submission, upload_session_id)
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
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    group = await ClientGroupRepository(session).get_by_token(token)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload link was not found")

    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if not submission or submission.group_id != group.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passport submission was not found")
    _require_public_upload_credential(submission, upload_session_id)

    try:
        content = await MinioStorageRepository().get_file(submission.image_s3_key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        )
    return StreamingResponse(
        io.BytesIO(content),
        media_type=mimetypes.guess_type(submission.image_s3_key)[0] or "image/jpeg",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'inline; filename="passport.jpg"',
        },
    )


def _get_staff_approve_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> StaffApprovePassportUseCase:
    return StaffApprovePassportUseCase(
        passport_repo=PassportSubmissionRepository(session)
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


def _get_retry_post_submission_verification_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RetryPostSubmissionVerificationUseCase:
    return RetryPostSubmissionVerificationUseCase(
        passport_repo=PassportSubmissionRepository(session)
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
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    group = await ClientGroupRepository(session).get_by_token(token)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload link was not found")

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
    }
    if document_type not in keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose front, back, or photo.",
        )
    key = keys[document_type]
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested passport document was not uploaded.",
        )
    try:
        content = await MinioStorageRepository().get_file(key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        )
    return StreamingResponse(
        io.BytesIO(content),
        media_type=mimetypes.guess_type(key)[0] or "image/jpeg",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="passport-{document_type}"',
        },
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
    submission_repo = PassportSubmissionRepository(session)
    submission = await submission_repo.get_by_id_for_update(submission_id)
    if not group or not submission or submission.group_id != group.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passport draft was not found")
    try:
        _require_public_upload_credential(submission, upload_session_id)
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport draft was not found",
        ) from exc
    if submission.status.value in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Submitted passports cannot be discarded")

    keys = [
        key for key in (
            submission.image_s3_key,
            submission.thumbnail_s3_key,
            submission.passport_photo_s3_key,
            submission.passport_back_s3_key,
        ) if key
    ]
    await submission_repo.delete(submission.id)
    # Remove the live database reference first. A failed commit leaves all
    # stored pages intact; post-commit object cleanup is best effort.
    await session.commit()
    try:
        await MinioStorageRepository().delete_files(keys)
    except StorageError as exc:
        logger.warning(
            "discarded_passport_object_cleanup_deferred",
            submission_id=str(submission.id),
            object_count=len(keys),
            error_type=type(exc).__name__,
        )
    record_operational_event(
        OperationalEvent.PUBLIC_FLOW,
        "upload_abandoned",
    )
    return {"discarded": True}


@router.get(
    "/groups",
    response_model=list[PassportGroupSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List client groups that contain passport submissions",
)
async def list_passport_groups(
    current_user: User = Depends(get_current_active_user),
    use_case: ListPassportGroupSummariesUseCase = Depends(_get_list_passport_groups_use_case),
    skip: int = 0,
    limit: int = 50,
) -> list[PassportGroupSummaryResponse]:
    if not current_user.agency_id:
        return []

    result = await use_case.execute(
        agency_id=current_user.agency_id,
        skip=skip,
        limit=limit,
        created_by_user_id=_owner_scope_for(current_user),
        visible_to_user=current_user,
    )
    return [PassportGroupSummaryResponse.model_validate(item) for item in result]


@router.get(
    "/groups/{group_id}",
    response_model=list[PassportSubmissionResponse],
    status_code=status.HTTP_200_OK,
    summary="List passport submissions within a client group",
)
async def list_passports_by_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    use_case: ListPassportSubmissionsByGroupUseCase = Depends(_get_list_passports_by_group_use_case),
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    include_deleted: bool = False,
) -> list[PassportSubmissionResponse]:
    if not current_user.agency_id:
        return []
    if include_deleted and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only super admins can view old data")

    result = await use_case.execute(
        agency_id=current_user.agency_id,
        group_id=group_id,
        skip=skip,
        limit=limit,
        search=search,
        created_by_user_id=None if include_deleted else _owner_scope_for(current_user),
        include_deleted_group=include_deleted,
        visible_to_user=None if include_deleted else current_user,
    )
    return [PassportSubmissionResponse.model_validate(item) for item in result]


@router.get(
    "/groups/{group_id}/submissions-view",
    response_model=PassportSubmissionsViewResponse,
    status_code=status.HTTP_200_OK,
    summary="List a full-group filtered and duplicate-aware submission view",
)
async def list_passports_by_group_view(
    group_id: uuid.UUID,
    submission_filter: Literal[
        "all",
        "pending_ai",
        "ai_approved",
        "needs_review",
        "staff_approved",
        "duplicates",
    ] = "all",
    sort_by: Literal[
        "name", "updated_at", "verification_confidence"
    ] = "name",
    sort_order: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=200),
    include_deleted: bool = False,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    use_case: ListPassportSubmissionsByGroupUseCase = Depends(
        _get_list_passports_by_group_use_case
    ),
) -> PassportSubmissionsViewResponse:
    if not current_user.agency_id:
        return PassportSubmissionsViewResponse(
            items=[],
            group_total=0,
            total=0,
            page=page,
            page_size=page_size,
            total_pages=0,
            returned_count=0,
            expiry_alerts=[],
        )
    if include_deleted and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super admins can view old data",
        )

    # Identity clusters, search propagation, and status filtering must operate
    # over the complete authorized group before block-aware pagination.
    all_submissions = await use_case.execute(
        agency_id=current_user.agency_id,
        group_id=group_id,
        skip=0,
        limit=None,
        search=None,
        created_by_user_id=(
            None if include_deleted else _owner_scope_for(current_user)
        ),
        include_deleted_group=include_deleted,
        visible_to_user=None if include_deleted else current_user,
    )
    travel_date_stmt = select(ClientGroupModel.travel_date).where(
        ClientGroupModel.id == group_id
    )
    if not include_deleted:
        travel_date_stmt = travel_date_stmt.where(
            ClientGroupModel.deleted_at.is_(None)
        )
    travel_date_stmt = AuthorizationPolicy.apply_group_visibility_scope(
        travel_date_stmt,
        current_user,
    )
    travel_date = (
        await session.execute(travel_date_stmt)
    ).scalar_one_or_none()
    view = build_submission_view(
        all_submissions,
        submission_filter=submission_filter,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
        page=page,
        page_size=page_size,
        travel_date=travel_date,
    )
    items: list[PassportSubmissionViewItemResponse] = []
    for entry in view.items:
        base = PassportSubmissionResponse.model_validate(
            entry.submission
        )
        items.append(
            PassportSubmissionViewItemResponse.model_validate(
                {
                    **base.model_dump(),
                    "duplicate_cluster_id": (
                        entry.duplicate_cluster_id
                    ),
                    "duplicate_cluster_size": (
                        entry.duplicate_cluster_size
                    ),
                    "duplicate_cluster_member_ids": list(
                        entry.duplicate_cluster_member_ids
                    ),
                    "verification_confidence": (
                        entry.verification_confidence
                    ),
                }
            )
        )
    return PassportSubmissionsViewResponse(
        items=items,
        group_total=view.group_total,
        total=view.total,
        page=view.page,
        page_size=view.page_size,
        total_pages=view.total_pages,
        returned_count=view.returned_count,
        cluster_boundaries_preserved=True,
        expiry_alerts=[
            PassportExpiryAlertResponse(
                submission_id=alert.submission_id,
                client_name=alert.client_name,
                client_email=alert.client_email,
                passport_number=alert.passport_number,
                date_of_expiry=alert.date_of_expiry,
                status=alert.status,
            )
            for alert in view.expiry_alerts
        ],
    )


@router.post(
    "/groups/{group_id}/bulk-delete",
    response_model=BulkDeletePassportSubmissionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Permanently delete selected passport submissions from a group",
)
async def bulk_delete_passport_submissions(
    group_id: uuid.UUID,
    body: BulkDeletePassportSubmissionsRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> BulkDeletePassportSubmissionsResponse:
    if current_user.role != UserRole.SUPER_ADMIN and not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    group = await ClientGroupRepository(session).get_by_id(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_delete_data(
            current_user,
            group,
            permanent=True,
        )
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc

    submission_ids = list(dict.fromkeys(body.submission_ids))
    selected_rows = await session.execute(
        select(
            PassportSubmissionModel.id,
            PassportSubmissionModel.image_s3_key,
            PassportSubmissionModel.thumbnail_s3_key,
            PassportSubmissionModel.passport_back_s3_key,
            PassportSubmissionModel.passport_photo_s3_key,
        )
        .where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.id.in_(submission_ids),
        )
        .with_for_update()
    )
    submissions = list(selected_rows.all())
    found_ids = {row.id for row in submissions}
    missing_ids = [
        submission_id
        for submission_id in submission_ids
        if submission_id not in found_ids
    ]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "One or more selected passport submissions were not found "
                "in this group. Refresh the page and try again."
            ),
        )

    storage_keys = passport_storage_keys(submissions)
    notification_result = await session.execute(
        delete(NotificationModel).where(
            NotificationModel.agency_id == group.agency_id,
            NotificationModel.entity_type == "passport_submission",
            NotificationModel.entity_id.in_(
                [str(submission_id) for submission_id in submission_ids]
            ),
        )
    )
    deleted_notifications = int(
        getattr(notification_result, "rowcount", 0) or 0
    )
    delete_result = await session.execute(
        delete(PassportSubmissionModel).where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.id.in_(submission_ids),
        )
    )
    deleted_count = int(getattr(delete_result, "rowcount", 0) or 0)
    if deleted_count != len(submission_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The selected submissions changed while deletion was in "
                "progress. Refresh the page and try again."
            ),
        )

    await AuditLogRepository(session).record(
        action="passport_submissions_bulk_deleted",
        entity_type="client_group",
        entity_id=str(group_id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "deleted_count": deleted_count,
            "deleted_submission_ids": [
                str(submission_id) for submission_id in submission_ids
            ],
            "storage_objects_scheduled_for_cleanup": len(storage_keys),
            "deleted_notifications": deleted_notifications,
        },
    )
    # Commit the authoritative database deletion before touching object
    # storage. A failed commit therefore leaves every passport file intact.
    await session.commit()

    deleted_storage_objects = 0
    storage_cleanup_deferred = False
    try:
        deleted_storage_objects = (
            await MinioStorageRepository().delete_files(storage_keys)
        )
    except StorageError as exc:
        storage_cleanup_deferred = True
        logger.warning(
            "passport_bulk_delete_storage_cleanup_deferred",
            group_id=str(group_id),
            submission_count=deleted_count,
            object_count=len(storage_keys),
            error_type=type(exc).__name__,
        )

    return BulkDeletePassportSubmissionsResponse(
        deleted_count=deleted_count,
        deleted_submission_ids=submission_ids,
        deleted_storage_objects=deleted_storage_objects,
        deleted_notifications=deleted_notifications,
        storage_cleanup_deferred=storage_cleanup_deferred,
    )


@router.get(
    "",
    response_model=list[PassportSubmissionResponse],
    status_code=status.HTTP_200_OK,
    summary="List passport submissions for the current agency",
)
async def list_passports(
    current_user: User = Depends(get_current_active_user),
    use_case: ListPassportSubmissionsUseCase = Depends(_get_list_passports_use_case),
    skip: int = 0,
    limit: int = 100,
    status_filter: str | None = None,
    search: str | None = None,
) -> list[PassportSubmissionResponse]:
    if not current_user.agency_id:
        return []

    result = await use_case.execute(
        agency_id=current_user.agency_id,
        skip=skip,
        limit=limit,
        status_filter=status_filter,
        search=search,
        created_by_user_id=_owner_scope_for(current_user),
        visible_to_user=current_user,
    )
    return [PassportSubmissionResponse.model_validate(item) for item in result]


@router.get(
    "/groups/{group_id}/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export a client group's passport submissions to Excel",
)
async def export_passports_by_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    group_repo = ClientGroupRepository(session)
    group = await group_repo.get_by_id(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found")
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)

    passport_repo = PassportSubmissionRepository(session)
    submissions = await passport_repo.list_by_group(
        current_user.agency_id,
        group_id,
        limit=5000,
        exclude_archived_groups=True,
        created_by_user_id=_owner_scope_for(current_user),
        visible_to_user=current_user,
    )
    content = PassportExcelExporter().export_group(
        submissions,
        group_name=group.name,
        group_details={group.id: _group_export_details(group)},
    )

    await AuditLogRepository(session).record(
        action="passport_group_exported",
        entity_type="client_group",
        entity_id=str(group_id),
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={"submission_count": len(submissions)},
    )

    filename = f"passport-export-{group_id}.xlsx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/groups/{group_id}/export-images",
    status_code=status.HTTP_200_OK,
    summary="Export a client group's original passport images as ZIP",
)
async def export_passport_images_by_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    group = await ClientGroupRepository(session).get_by_id(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found")
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)

    submissions = await PassportSubmissionRepository(session).list_by_group(
        current_user.agency_id,
        group_id,
        limit=PassportImageZipExporter.MAX_SUBMISSIONS + 1,
        exclude_archived_groups=True,
        created_by_user_id=_owner_scope_for(current_user),
        visible_to_user=current_user,
    )
    try:
        spool, image_count, uncompressed_bytes = await PassportImageZipExporter().export_group(
            submissions,
            group_name=group.name,
            staff_code_enabled=group.staff_code_enabled,
            storage=MinioStorageRepository(),
        )
    except MissingPassportImagesError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except PassportImageExportLimitError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc))
    except StorageError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="One or more original images could not be read from secure storage.",
        )

    spool.seek(0, io.SEEK_END)
    archive_size = spool.tell()
    spool.seek(0)
    await AuditLogRepository(session).record(
        action="passport_group_images_exported",
        entity_type="client_group",
        entity_id=str(group_id),
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "submission_count": len(submissions),
            "image_count": image_count,
            "uncompressed_bytes": uncompressed_bytes,
            "archive_bytes": archive_size,
        },
    )

    filename = safe_download_filename(group.name)
    return StreamingResponse(
        _stream_binary_file(spool),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(archive_size),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/groups/{group_id}/import.xlsx",
    response_model=ImportPassportGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import passport submissions into a client group from Excel",
)
async def import_passports_by_group(
    group_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ImportPassportGroupResponse:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    group_repo = ClientGroupRepository(session)
    group = await group_repo.get_by_id(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found")
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload an .xlsx Excel file")

    try:
        content = await file.read()
        rows = PassportExcelImporter().import_rows(content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to read the Excel file")

    result = await session.execute(select(PassportSubmissionModel).where(PassportSubmissionModel.group_id == group.id))
    existing_submissions = list(result.scalars().all())
    existing_by_staff_code = {
        code: submission
        for submission in existing_submissions
        if (code := _staff_code_for_submission(submission))
    }
    existing_by_identity = {
        _excel_identity_key(submission.client_name, submission.client_email, submission.client_phone): submission
        for submission in existing_submissions
    }

    now = datetime.now(tz=UTC)
    models: list[PassportSubmissionModel] = []
    updated_count = 0
    seen_import_keys: set[str] = set()
    for row in rows:
        row_staff_code = str((row.staff_metadata or {}).get("staff_code") or row.confirmed_fields.get("staff_code") or "").strip().upper()
        row_identity = _excel_identity_key(row.client_name, row.client_email, row.client_phone)
        import_key = row_staff_code or row_identity
        if import_key in seen_import_keys:
            continue
        seen_import_keys.add(import_key)

        existing = existing_by_staff_code.get(row_staff_code) if row_staff_code else existing_by_identity.get(row_identity)
        if existing:
            existing.client_name = row.client_name
            existing.client_email = row.client_email
            existing.client_phone = row.client_phone
            existing.departure_city = row.departure_city
            existing.nearest_domestic_airport = row.nearest_domestic_airport
            existing.staff_metadata = row.staff_metadata or existing.staff_metadata
            existing.confirmed_fields = _merge_excel_fields(existing.confirmed_fields, row.confirmed_fields)
            existing.extracted_fields = _merge_excel_fields(existing.extracted_fields, row.confirmed_fields)
            existing.confidence_score = {
                **(existing.confidence_score or {}),
                "source": "excel_import",
                "row_number": row.row_number,
                "source_sheet": row.worksheet_name,
                "updated_from_excel": True,
            }
            existing.overall_confidence = existing.overall_confidence if existing.overall_confidence is not None else (1.0 if row.confirmed_fields else None)
            existing.updated_at = now
            updated_count += 1
            continue

        submission_id = uuid.uuid4()
        models.append(
            PassportSubmissionModel(
                id=submission_id,
                group_id=group.id,
                agency_id=group.agency_id,
                client_name=row.client_name,
                client_email=row.client_email,
                client_phone=row.client_phone,
                departure_city=row.departure_city,
                nearest_domestic_airport=row.nearest_domestic_airport,
                image_s3_key=f"excel-imports/{group.id}/{submission_id}.placeholder",
                status="client_submitted",
                confirmed_fields=row.confirmed_fields or None,
                extracted_fields=row.confirmed_fields or None,
                staff_metadata=row.staff_metadata or None,
                overall_confidence=1.0 if row.confirmed_fields else None,
                confidence_score={"source": "excel_import", "row_number": row.row_number, "source_sheet": row.worksheet_name},
                client_reviewed_at=now,
                created_at=now,
                updated_at=now,
            )
        )

    if models:
        session.add_all(models)
    if models or updated_count:
        await AuditLogRepository(session).record(
            action="passport_group_imported",
            entity_type="client_group",
            entity_id=str(group_id),
            agency_id=group.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={"imported_count": len(models), "updated_count": updated_count, "filename": file.filename},
        )
        await session.commit()

    return ImportPassportGroupResponse(
        imported_count=len(models),
        updated_count=updated_count,
        skipped_count=max(len(rows) - len(models) - updated_count, 0),
    )


def _excel_identity_key(name: str | None, email: str | None, phone: str | None) -> str:
    parts = [name or "", email or "", phone or ""]
    return "|".join(part.strip().casefold() for part in parts)


def _merge_excel_fields(existing: dict | None, imported: dict) -> dict | None:
    if not existing:
        return imported or None
    merged = dict(existing)
    for key, value in imported.items():
        if value not in (None, ""):
            merged[key] = value
    return merged


def _staff_code_for_submission(submission: PassportSubmissionModel) -> str | None:
    metadata = getattr(submission, "staff_metadata", None) or {}
    fields = submission.confirmed_fields or submission.extracted_fields or {}
    value = metadata.get("staff_code") or fields.get("staff_code")
    return str(value).strip().upper() if value else None


async def _authorized_passport_document_group(
    group_id: uuid.UUID, current_user: User, session: AsyncSession
) -> ClientGroupModel:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    group = await ClientGroupRepository(session).get_by_id(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found")
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    return group


async def _passport_document_preview(
    *, group_id: uuid.UUID, files: list[UploadFile], session: AsyncSession
) -> tuple[PassportDocumentImportPreviewResponse, list[PassportDocumentFile]]:
    result = await session.execute(select(PassportSubmissionModel).where(PassportSubmissionModel.group_id == group_id))
    submissions = list(result.scalars().all())
    by_staff_code = {code: submission for submission in submissions if (code := _staff_code_for_submission(submission))}
    payloads: list[tuple[str, bytes, str | None]] = []
    for file in files:
        try:
            payloads.append((file.filename or "upload", await file.read(), file.content_type))
        except Exception:
            payloads.append((file.filename or "upload", b"", file.content_type))
    accepted, rejected = PassportDocumentImporter().collect(payloads, allowed_staff_codes=set(by_staff_code))
    response_accepted: list[PassportDocumentImportItem] = []
    matched: list[PassportDocumentFile] = []
    seen: set[tuple[uuid.UUID, str]] = set()
    for item in accepted:
        submission = by_staff_code.get(item.staff_code)
        if not submission:
            rejected.append(RejectedPassportDocument(item.filename, "Staff code was not found in this group"))
            continue
        key = (submission.id, item.document_type)
        if key in seen:
            rejected.append(RejectedPassportDocument(item.filename, "Duplicate document type for this passenger"))
            continue
        seen.add(key)
        matched.append(item)
        response_accepted.append(PassportDocumentImportItem(
            filename=item.filename, staff_code=item.staff_code, document_type=item.document_type,
            passenger_id=submission.id, passenger_name=submission.client_name, accepted=True,
        ))
    response_rejected = [PassportDocumentImportItem(filename=item.filename, accepted=False, reason=item.reason) for item in rejected]
    return PassportDocumentImportPreviewResponse(
        group_id=group_id,
        total_count=len(response_accepted) + len(response_rejected),
        accepted_count=len(response_accepted), rejected_count=len(response_rejected),
        accepted_documents=response_accepted, rejected_documents=response_rejected,
    ), matched


@router.post("/groups/{group_id}/import-passports/preview", response_model=PassportDocumentImportPreviewResponse)
async def preview_passport_documents_by_group(
    group_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportDocumentImportPreviewResponse:
    await _authorized_passport_document_group(group_id, current_user, session)
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose one or more images or ZIP archives")
    preview, _ = await _passport_document_preview(group_id=group_id, files=files, session=session)
    return preview


@router.post("/groups/{group_id}/import-passports/save", response_model=PassportDocumentImportSaveResponse)
async def save_passport_documents_by_group(
    group_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportDocumentImportSaveResponse:
    group = await _authorized_passport_document_group(group_id, current_user, session)
    if not any((file.filename or "").lower().endswith(".zip") for file in files):
        return await _save_loose_passport_documents_by_group(
            group=group,
            group_id=group_id,
            files=files,
            current_user=current_user,
            session=session,
            background_tasks=background_tasks,
        )

    preview, matched = await _passport_document_preview(group_id=group_id, files=files, session=session)
    if not matched:
        return PassportDocumentImportSaveResponse(**preview.model_dump(), saved_count=0)

    result = await session.execute(select(PassportSubmissionModel).where(PassportSubmissionModel.group_id == group_id))
    by_staff_code = {code: submission for submission in result.scalars().all() if (code := _staff_code_for_submission(submission))}
    storage = MinioStorageRepository()
    uploaded_keys: list[str] = []
    replaced_keys: list[str] = []
    try:
        for item in matched:
            submission = by_staff_code[item.staff_code]
            attr = {"front": "image_s3_key", "photo": "passport_photo_s3_key", "back": "passport_back_s3_key"}[item.document_type]
            old_key = getattr(submission, attr, None)
            suffix = item.upload.filename.rsplit(".", 1)[-1]
            key = f"passport-bulk/{group.agency_id}/{group.id}/{submission.id}/{item.document_type}.{suffix}"
            await storage.upload_file(item.upload.content, key, item.upload.content_type)
            uploaded_keys.append(key)
            setattr(submission, attr, key)
            if old_key and not old_key.startswith("excel-imports/") and old_key != key:
                replaced_keys.append(old_key)
        await AuditLogRepository(session).record(
            action="passport_documents_bulk_imported", entity_type="client_group", entity_id=str(group_id),
            agency_id=group.agency_id, user_id=current_user.id, actor_email=current_user.email,
            metadata={"saved_count": len(matched), "rejected_count": preview.rejected_count},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        await storage.delete_files(uploaded_keys)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save passport documents; no imported files were retained")
    if replaced_keys:
        await storage.delete_files(replaced_keys)
    # OCR is only useful once the complete staff bundle is present. It enriches
    # blanks through PassportSubmission.mark_review_required without replacing
    # values imported from Excel.
    ocr_targets = []
    required_fields = ("passport_number", "surname", "given_names", "date_of_birth", "date_of_expiry")
    for submission in {by_staff_code[item.staff_code].id: by_staff_code[item.staff_code] for item in matched}.values():
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        has_all_images = bool(submission.image_s3_key) and bool(getattr(submission, "passport_photo_s3_key", None)) and bool(getattr(submission, "passport_back_s3_key", None))
        if has_all_images and any(not str(fields.get(field, "")).strip() for field in required_fields):
            ocr_targets.append(submission.id)
    if ocr_targets:
        reextract = ReextractPassportSubmissionUseCase(
            passport_repo=PassportSubmissionRepository(session),
            processing_job_repo=PassportProcessingJobRepository(session),
        )
        jobs = [await reextract.execute(submission_id) for submission_id in ocr_targets]
        await session.commit()
        for job in jobs:
            if job.processing_job_id:
                PassportProcessingDispatcher().dispatch(
                    job_id=job.processing_job_id, submission_id=job.id, background_tasks=background_tasks,
                )
    return PassportDocumentImportSaveResponse(**preview.model_dump(), saved_count=len(matched))


async def _save_loose_passport_documents_by_group(
    *,
    group: ClientGroupModel,
    group_id: uuid.UUID,
    files: list[UploadFile],
    current_user: User,
    session: AsyncSession,
    background_tasks: BackgroundTasks,
) -> PassportDocumentImportSaveResponse:
    result = await session.execute(select(PassportSubmissionModel).where(PassportSubmissionModel.group_id == group_id))
    by_staff_code = {code: submission for submission in result.scalars().all() if (code := _staff_code_for_submission(submission))}
    importer = PassportDocumentImporter()
    storage = MinioStorageRepository()
    uploaded_keys: list[str] = []
    replaced_keys: list[str] = []
    accepted_documents: list[PassportDocumentImportItem] = []
    rejected_documents: list[PassportDocumentImportItem] = []
    seen: set[tuple[uuid.UUID, str]] = set()
    touched_submissions: dict[uuid.UUID, PassportSubmissionModel] = {}

    try:
        for file in files:
            filename = file.filename or "upload"
            accepted, rejected = importer.collect(
                [(filename, await file.read(), file.content_type)],
                allowed_staff_codes=set(by_staff_code),
            )
            rejected_documents.extend(PassportDocumentImportItem(filename=item.filename, accepted=False, reason=item.reason) for item in rejected)
            for item in accepted:
                submission = by_staff_code.get(item.staff_code)
                if not submission:
                    rejected_documents.append(PassportDocumentImportItem(filename=item.filename, accepted=False, reason="Staff code was not found in this group"))
                    continue
                duplicate_key = (submission.id, item.document_type)
                if duplicate_key in seen:
                    rejected_documents.append(PassportDocumentImportItem(filename=item.filename, accepted=False, reason="Duplicate document type for this passenger"))
                    continue
                seen.add(duplicate_key)

                attr = {"front": "image_s3_key", "photo": "passport_photo_s3_key", "back": "passport_back_s3_key"}[item.document_type]
                old_key = getattr(submission, attr, None)
                suffix = item.upload.filename.rsplit(".", 1)[-1]
                key = f"passport-bulk/{group.agency_id}/{group.id}/{submission.id}/{item.document_type}.{suffix}"
                await storage.upload_file(item.upload.content, key, item.upload.content_type)
                uploaded_keys.append(key)
                setattr(submission, attr, key)
                submission.updated_at = datetime.now(tz=UTC)
                touched_submissions[submission.id] = submission
                accepted_documents.append(PassportDocumentImportItem(
                    filename=item.filename,
                    staff_code=item.staff_code,
                    document_type=item.document_type,
                    passenger_id=submission.id,
                    passenger_name=submission.client_name,
                    accepted=True,
                ))
                if old_key and not old_key.startswith("excel-imports/") and old_key != key:
                    replaced_keys.append(old_key)

        if accepted_documents:
            await AuditLogRepository(session).record(
                action="passport_documents_bulk_imported",
                entity_type="client_group",
                entity_id=str(group_id),
                agency_id=group.agency_id,
                user_id=current_user.id,
                actor_email=current_user.email,
                metadata={"saved_count": len(accepted_documents), "rejected_count": len(rejected_documents), "streamed": True},
            )
            await session.commit()
        else:
            await session.rollback()
    except Exception:
        await session.rollback()
        await storage.delete_files(uploaded_keys)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save passport documents; no imported files were retained")

    if replaced_keys:
        await storage.delete_files(replaced_keys)

    await _queue_ocr_for_complete_staff_bundles(
        submissions=list(touched_submissions.values()),
        session=session,
        background_tasks=background_tasks,
    )
    return PassportDocumentImportSaveResponse(
        group_id=group_id,
        total_count=len(accepted_documents) + len(rejected_documents),
        accepted_count=len(accepted_documents),
        rejected_count=len(rejected_documents),
        accepted_documents=accepted_documents,
        rejected_documents=rejected_documents,
        saved_count=len(accepted_documents),
    )


async def _queue_ocr_for_complete_staff_bundles(
    *,
    submissions: list[PassportSubmissionModel],
    session: AsyncSession,
    background_tasks: BackgroundTasks,
) -> None:
    required_fields = ("passport_number", "surname", "given_names", "date_of_birth", "date_of_expiry")
    ocr_targets = []
    for submission in submissions:
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        has_all_images = bool(submission.image_s3_key) and bool(getattr(submission, "passport_photo_s3_key", None)) and bool(getattr(submission, "passport_back_s3_key", None))
        if has_all_images and any(not str(fields.get(field, "")).strip() for field in required_fields):
            ocr_targets.append(submission.id)
    if not ocr_targets:
        return
    reextract = ReextractPassportSubmissionUseCase(
        passport_repo=PassportSubmissionRepository(session),
        processing_job_repo=PassportProcessingJobRepository(session),
    )
    jobs = [await reextract.execute(submission_id) for submission_id in ocr_targets]
    await session.commit()
    for job in jobs:
        if job.processing_job_id:
            PassportProcessingDispatcher().dispatch(
                job_id=job.processing_job_id,
                submission_id=job.id,
                background_tasks=background_tasks,
            )


@router.post(
    "/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export selected passport submissions to Excel",
)
async def export_selected_passports(
    body: ExportSelectedPassportsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    stmt = (
        select(PassportSubmissionModel)
        .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        .where(
            PassportSubmissionModel.id.in_(body.submission_ids),
            PassportSubmissionModel.status.in_(_submitted_statuses()),
        )
    )
    stmt = _apply_manager_visibility(stmt, current_user)
    result = await session.execute(stmt)
    submissions = [PassportSubmissionRepository._to_entity(model) for model in result.scalars().all()]
    if not submissions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No exportable passport submissions found")

    content = PassportExcelExporter().export_group(
        submissions,
        group_name="Selected Passports",
        group_details=await _export_group_details(session, [submission.group_id for submission in submissions]),
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="selected-passports.xlsx"'},
    )


@router.post(
    "/groups/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export selected passport groups to Excel",
)
async def export_selected_groups(
    body: ExportSelectedGroupsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    stmt = (
        select(PassportSubmissionModel)
        .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        .where(
            PassportSubmissionModel.group_id.in_(body.group_ids),
            PassportSubmissionModel.status.in_(_submitted_statuses()),
        )
    )
    stmt = _apply_manager_visibility(stmt, current_user)
    result = await session.execute(stmt)
    submissions = [PassportSubmissionRepository._to_entity(model) for model in result.scalars().all()]
    if not submissions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No exportable passport submissions found")

    content = PassportExcelExporter().export_group(
        submissions,
        group_name="Selected Groups",
        group_details=await _export_group_details(session, body.group_ids),
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="selected-groups-passports.xlsx"'},
    )


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

        job = await PassportProcessingJobRepository(session).latest_for_submission(
            result.id
        )
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


@router.post(
    "/{submission_id}/client-submit",
    response_model=PassportSubmissionResponse,
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
    existing = await PassportSubmissionRepository(session).get_by_id(
        submission_id
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport submission was not found",
        )
    _require_public_upload_credential(existing, upload_session_id)

    result: PassportSubmissionOutputDTO | None = None
    verification_job = None
    committed = False
    commit_attempted = False
    try:
        result = await use_case.execute(
            submission_id,
            group_token=body.group_token,
            confirmed_fields=body.confirmed_fields,
            client_email=str(body.client_email) if body.client_email else None,
            client_phone=body.client_phone,
            departure_city=body.departure_city,
            nearest_domestic_airport=body.nearest_domestic_airport,
            base_city=body.base_city,
            staff_code=body.staff_code,
            meal_preference=body.meal_preference,
            submission_mode=body.submission_mode,
            family_group_id=body.family_group_id,
            family_member_index=body.family_member_index,
            family_relation=body.family_relation,
            family_gender=body.family_gender,
            family_head_name=body.family_head_name,
            family_head_email=str(body.family_head_email) if body.family_head_email else None,
            family_head_phone=body.family_head_phone,
        )
        verification_job = await PostSubmissionVerificationJobRepository(
            session
        ).enqueue(
            submission_id=result.id,
            verification_revision=result.post_submission_verification_revision,
        )
        if not result.idempotent_replay:
            await AuditLogRepository(session).record(
                action="client_passport_submitted",
                entity_type="passport_submission",
                entity_id=str(result.id),
                agency_id=result.agency_id,
                metadata={
                    "group_id": str(result.group_id),
                    "submission_mode": result.submission_mode,
                    "qualifier_enabled_snapshot": (
                        result.qualifier_enabled_snapshot
                    ),
                },
            )
            await NotificationRepository(session).create(
                agency_id=result.agency_id,
                type="passport_submitted",
                title="Client passport submitted",
                message="A client submitted reviewed passport details.",
                entity_type="passport_submission",
                entity_id=str(result.id),
            )
        # Commit the DB transition before deleting superseded draft objects.
        # A failed commit therefore leaves the original draft keys intact and
        # the traveller can retry safely.
        commit_attempted = True
        await session.commit()
        committed = True
        task_id = None
        if verification_job.status == "queued":
            task_id = PostSubmissionVerificationDispatcher().dispatch(
                job_id=verification_job.id,
                submission_id=result.id,
                verification_revision=result.post_submission_verification_revision,
                background_tasks=background_tasks,
            )
        if task_id:
            try:
                await PostSubmissionVerificationJobRepository(session).set_task_id(
                    verification_job.id,
                    task_id,
                )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.warning(
                    "post_submission_verification_task_id_persist_failed",
                    job_id=str(verification_job.id),
                    error_type=type(exc).__name__,
                )
        if result.storage_cleanup_keys:
            try:
                await MinioStorageRepository().delete_files(
                    list(result.storage_cleanup_keys)
                )
            except StorageError as exc:
                logger.warning(
                    "passport_draft_cleanup_deferred",
                    submission_id=str(result.id),
                    object_count=len(result.storage_cleanup_keys),
                    error_type=type(exc).__name__,
                )
        return PassportSubmissionResponse.model_validate(result)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except PassDetectionError as e:
        if not committed and not commit_attempted:
            await _cleanup_uncommitted_promotions(result)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    except Exception:
        # Once commit was attempted its outcome can be ambiguous after a
        # connection loss. Deleting promoted objects could break a row that
        # PostgreSQL actually committed, so compensate only pre-commit errors.
        if not committed and not commit_attempted:
            await _cleanup_uncommitted_promotions(result)
        raise


@router.post(
    "/{submission_id}/staff-approve",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve a passport that needs post-submission review",
)
async def staff_approve_passport(
    submission_id: uuid.UUID,
    body: StaffApprovePassportRequest,
    response: Response,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    approve_use_case: StaffApprovePassportUseCase = Depends(
        _get_staff_approve_passport_use_case
    ),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse | JSONResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_staff_approve_passport(
            current_user,
            existing,
        )
        approval: StaffApprovalResult = await approve_use_case.execute(
            submission_id,
            reviewer_id=current_user.id,
            reviewer_name=current_user.full_name,
            confirmed_fields=body.confirmed_fields,
            expected_extraction_revision=body.expected_extraction_revision,
            review_reason=body.review_reason,
        )
        result = approval.submission
        if approval.outcome is StaffApprovalOutcome.APPROVED:
            audit_metadata: dict[str, object] = {
                "group_id": str(result.group_id),
                "prior_status": approval.previous_status,
                "new_status": result.status,
                "corrected_field_names": list(approval.corrected_field_names),
                "outcome": approval.outcome.value,
                "extraction_revision": result.extraction_revision,
                "verification_revision": (
                    result.post_submission_verification_revision
                ),
            }
            if approval.review_reason is not None:
                audit_metadata["review_reason"] = approval.review_reason
            await AuditLogRepository(session).record(
                action="passport_staff_approved",
                entity_type="passport_submission",
                entity_id=str(result.id),
                agency_id=result.agency_id,
                user_id=current_user.id,
                metadata=audit_metadata,
            )
            await _ensure_submission_qr(session, result.id, current_user.id)

        # The locked transition, audit row, and first QR issuance are one
        # transaction. Commit before presigned-URL work so the row lock is
        # released and a lost response can be retried idempotently.
        await session.commit()
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            (
                "approved"
                if approval.outcome is StaffApprovalOutcome.APPROVED
                else "already_approved"
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Staff-Approval-Outcome"] = approval.outcome.value
        response.headers["X-Staff-Approval-Revision"] = str(
            result.extraction_revision
        )
        return await _response_from_dto(result, session=session)
    except (StaffApprovalStaleError, StaffApprovalUnavailableError) as exc:
        # The typed conflict is raised while the submission row is locked.
        # Release that lock before returning the retry-safe 409 response.
        await session.rollback()
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            (
                "stale"
                if isinstance(exc, StaffApprovalStaleError)
                else "unavailable"
            ),
        )
        return _staff_approval_conflict_response(exc)
    except EntityNotFoundError as exc:
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "not_found",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        )
    except AuthorizationError as exc:
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "forbidden",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        )
    except Exception:
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "unexpected_failure",
        )
        raise


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
        verification_job = await PostSubmissionVerificationJobRepository(
            session
        ).enqueue(
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
                task_id = PostSubmissionVerificationDispatcher().dispatch(
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
                        await PostSubmissionVerificationJobRepository(
                            session
                        ).set_task_id(verification_job.id, task_id)
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
    reextract_use_case: ReextractPassportSubmissionUseCase = Depends(_get_reextract_passport_use_case),
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processing job was not found")

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


@router.post(
    "/{submission_id}/confirm",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm reviewed passport fields",
)
async def confirm_passport(
    submission_id: uuid.UUID,
    body: ConfirmPassportSubmissionRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    confirm_use_case: ConfirmPassportSubmissionUseCase = Depends(_get_confirm_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_confirm_passport(current_user, existing)

        result = await confirm_use_case.execute(
            submission_id,
            confirmed_fields=body.confirmed_fields,
        )
        await AuditLogRepository(session).record(
            action="passport_confirmed",
            entity_type="passport_submission",
            entity_id=str(result.id),
            agency_id=result.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
        )
        await _ensure_submission_qr(session, result.id, current_user.id)
        storage = MinioStorageRepository()
        image_url = await storage.get_presigned_url(result.image_s3_key)
        return PassportSubmissionResponse.model_validate({
            **result.__dict__, "image_url": image_url,
            "passport_photo_url": await storage.get_presigned_url(result.passport_photo_s3_key) if result.passport_photo_s3_key else None,
            "passport_back_url": await storage.get_presigned_url(result.passport_back_s3_key) if result.passport_back_s3_key else None,
        })
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
