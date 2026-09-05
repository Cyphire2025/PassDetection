"""Passport submission review: focused workflow boundary."""

from __future__ import annotations

import uuid
from dataclasses import replace

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
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
from app.application.use_cases.passports.reextract_passport_submission_use_case import (
    ReextractPassportSubmissionUseCase,
)
from app.application.use_cases.passports.retry_post_submission_verification_use_case import (
    RetryPostSubmissionVerificationUseCase,
)
from app.application.use_cases.passports.staff_approve_passport_use_case import (
    StaffApprovalResult,
    StaffApprovePassportUseCase,
)
from app.core.logging.logger import get_logger
from app.domain.entities.entities import StaffApprovalOutcome, User
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    EntityNotFoundError,
    PassDetectionError,
    StaffApprovalStaleError,
    StaffApprovalUnavailableError,
    StorageError,
)
from app.infrastructure.database.models import StorageCleanupJobModel
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
from app.infrastructure.repositories.notification_repository import NotificationRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.verification.dispatcher import PostSubmissionVerificationDispatcher
from app.infrastructure.verification.job_repository import (
    PostSubmissionVerificationJob,
    PostSubmissionVerificationJobRepository,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    ClientSubmitPassportRequest,
    ConfirmPassportSubmissionRequest,
    PassportSubmissionResponse,
    StaffApprovePassportRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .dependencies import (
    _get_client_submit_passport_use_case,
    _get_confirm_passport_use_case,
    _get_get_passport_use_case,
    _get_reextract_passport_use_case,
    _get_retry_post_submission_verification_use_case,
    _get_staff_approve_passport_use_case,
)
from .processing_support import _dispatch_processing_job
from .public_security import _require_public_upload_credential
from .response_support import _ensure_submission_qr, _response_from_dto, _response_from_submission

router = APIRouter()

logger = get_logger(__name__)


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
    existing = await PassportSubmissionRepository(session).get_by_id(submission_id)
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
    cleanup_jobs: tuple[StorageCleanupJobModel, ...] = ()
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
            agent_employee_type=body.agent_employee_type,
            agent_employee_code=body.agent_employee_code,
            designation=body.designation,
            agency_dealership_name=body.agency_dealership_name,
            meal_preference=body.meal_preference,
            submission_mode=body.submission_mode,
            family_group_id=body.family_group_id,
            family_member_index=body.family_member_index,
            family_relation=body.family_relation,
            family_gender=body.family_gender,
            family_head_name=body.family_head_name,
            family_head_email=str(body.family_head_email) if body.family_head_email else None,
            family_head_phone=body.family_head_phone,
            custom_answers=[answer.model_dump(mode="json") for answer in body.custom_answers],
            custom_detail_answers=[
                answer.model_dump(mode="json") for answer in body.custom_detail_answers
            ],
        )
        if result.image_s3_key:
            verification_job = await PostSubmissionVerificationJobRepository(session).enqueue(
                submission_id=result.id,
                verification_revision=result.post_submission_verification_revision,
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
            await AuditLogRepository(session).record(
                action="client_passport_submitted",
                entity_type="passport_submission",
                entity_id=str(result.id),
                agency_id=result.agency_id,
                metadata={
                    "group_id": str(result.group_id),
                    "submission_mode": result.submission_mode,
                    "qualifier_enabled_snapshot": (result.qualifier_enabled_snapshot),
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
        if result.storage_cleanup_keys:
            cleanup_jobs = stage_storage_cleanup_jobs(
                session,
                agency_id=result.agency_id,
                source="passport_submission_delete",
                context_id=f"client-submit:{result.group_id}:{result.id}",
                storage_keys=result.storage_cleanup_keys,
            )
        # Commit the DB transition before deleting superseded draft objects.
        # A failed commit therefore leaves the original draft keys intact and
        # the traveller can retry safely.
        commit_attempted = True
        await session.commit()
        committed = True
        await _dispatch_committed_verification(
            verification_job,
            result=result,
            session=session,
            background_tasks=background_tasks,
        )
        for cleanup_job in cleanup_jobs:
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
    approve_use_case: StaffApprovePassportUseCase = Depends(_get_staff_approve_passport_use_case),
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
                "verification_revision": (result.post_submission_verification_revision),
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
        response.headers["X-Staff-Approval-Revision"] = str(result.extraction_revision)
        return await _response_from_dto(result, session=session)
    except (StaffApprovalStaleError, StaffApprovalUnavailableError) as exc:
        # The typed conflict is raised while the submission row is locked.
        # Release that lock before returning the retry-safe 409 response.
        await session.rollback()
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            ("stale" if isinstance(exc, StaffApprovalStaleError) else "unavailable"),
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
        return await _response_from_dto(result, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
