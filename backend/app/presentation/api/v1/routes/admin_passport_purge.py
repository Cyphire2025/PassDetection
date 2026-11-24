"""Locked passport and broadcast purge with durable cleanup tombstones."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.destructive_mutation_policy import (
    DestructiveMutationPolicy,
    record_destructive_failure,
)
from app.core.logging.logger import get_logger
from app.domain.entities.entities import (
    User,
    UserRole,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    NotificationModel,
    PassportProcessingJobModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.storage_cleanup import (
    process_storage_cleanup_job,
    stage_storage_cleanup_jobs,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.storage.passport_object_keys import passport_storage_keys
from app.presentation.api.v1.routes.admin_deletion_queries import (
    _delete_by_ids,
    _delete_entity_rows,
    _delete_whatsapp_broadcast_data,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    PurgePassportDataResponse,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
logger = get_logger("app.presentation.api.v1.routes.admin")
PASSPORT_PURGE_INLINE_CLEANUP_MAX_OBJECTS = 500


@router.delete(
    "/passport-data",
    response_model=PurgePassportDataResponse,
    status_code=status.HTTP_200_OK,
    summary="Permanently delete passport and WhatsApp broadcast data",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def purge_passport_data(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> PurgePassportDataResponse:
    if current_user.role != UserRole.SUPER_ADMIN and not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This admin account is not assigned to an agency",
        )

    whatsapp_group_lock = select(WhatsAppBroadcastGroupModel.id).order_by(
        WhatsAppBroadcastGroupModel.id
    )
    if current_user.role != UserRole.SUPER_ADMIN:
        whatsapp_group_lock = whatsapp_group_lock.where(
            WhatsAppBroadcastGroupModel.agency_id == current_user.agency_id
        )
    await session.execute(whatsapp_group_lock.with_for_update())
    processing_filter = [WhatsAppRecipientMessageStateModel.status == "processing"]
    if current_user.role != UserRole.SUPER_ADMIN:
        processing_filter.append(
            WhatsAppRecipientMessageStateModel.agency_id == current_user.agency_id
        )
    processing_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppRecipientMessageStateModel)
        .where(*processing_filter)
    )
    if int(processing_result.scalar_one()) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A WhatsApp provider request is currently in progress. "
                "Wait for it to finish before deleting all data."
            ),
        )

    # Legal-hold changes and every other destructive group mutation lock these
    # same rows. The ordered scope lock makes the hold check and the ensuing
    # purge one serialized decision rather than a count-then-delete race.
    mutation = await DestructiveMutationPolicy(session).require_scoped_groups(
        user=current_user,
        action="passport_data_purge",
    )
    group_ids = [group.id for group in mutation.groups]
    # Even a platform purge is bounded to the rows in the locked group set.
    # A group inserted concurrently after the scope lock is therefore left
    # wholly intact instead of losing submissions while its group row survives.
    passport_filter = [PassportSubmissionModel.group_id.in_(group_ids)]

    submission_rows = await session.execute(
        select(
            PassportSubmissionModel.id,
            PassportSubmissionModel.image_s3_key,
            PassportSubmissionModel.thumbnail_s3_key,
            PassportSubmissionModel.passport_back_s3_key,
            PassportSubmissionModel.passport_cover_s3_key,
            PassportSubmissionModel.passport_back_cover_s3_key,
            PassportSubmissionModel.passport_photo_s3_key,
        )
        .where(*passport_filter)
        .order_by(PassportSubmissionModel.id)
        .with_for_update()
    )
    submissions = list(submission_rows.all())
    submission_ids = [row.id for row in submissions]
    storage_keys = passport_storage_keys(submissions)
    crop_repository = PassportImageCropRepository(session)
    storage_keys.extend(await crop_repository.derived_storage_keys(submission_ids))
    storage_keys.extend(await crop_repository.edit_storage_keys(submission_ids))

    # The encrypted cleanup rows are committed atomically with the authoritative
    # database deletion. Object storage is deliberately untouched until after
    # that commit, so neither a storage failure nor a database rollback can
    # leave retained rows pointing at files that have already disappeared.
    cleanup_jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=(None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id),
        source="passport_submission_delete",
        context_id=(
            "platform"
            if current_user.role == UserRole.SUPER_ADMIN
            else f"agency:{current_user.agency_id}"
        ),
        storage_keys=storage_keys,
    )

    group_entity_ids = [str(group_id) for group_id in group_ids]
    submission_entity_ids = [str(submission_id) for submission_id in submission_ids]

    deleted_notifications = await _delete_entity_rows(
        session,
        NotificationModel,
        agency_id=None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id,
        group_entity_ids=group_entity_ids,
        submission_entity_ids=submission_entity_ids,
    )
    # Security audit history is append-only application evidence and has its
    # own bounded retention/export lifecycle; a data purge must not erase it.
    deleted_audit_logs = 0

    deleted_processing_jobs = await _delete_by_ids(
        session,
        PassportProcessingJobModel,
        PassportProcessingJobModel.submission_id,
        submission_ids,
    )
    deleted_passport_submissions = await _delete_by_ids(
        session,
        PassportSubmissionModel,
        PassportSubmissionModel.id,
        submission_ids,
    )
    deleted_client_groups = await _delete_by_ids(
        session, ClientGroupModel, ClientGroupModel.id, group_ids
    )
    whatsapp_counts = await _delete_whatsapp_broadcast_data(
        session,
        agency_id=None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id,
    )

    response = PurgePassportDataResponse(
        deleted_client_groups=deleted_client_groups,
        deleted_passport_submissions=deleted_passport_submissions,
        deleted_processing_jobs=deleted_processing_jobs,
        deleted_notifications=deleted_notifications,
        deleted_audit_logs=deleted_audit_logs,
        deleted_storage_objects=0,
        deleted_whatsapp_broadcast_groups=whatsapp_counts.broadcast_groups,
        deleted_whatsapp_recipients=whatsapp_counts.recipients,
        deleted_whatsapp_rejected_contacts=whatsapp_counts.rejected_contacts,
        deleted_whatsapp_support_contacts=whatsapp_counts.support_contacts,
        deleted_whatsapp_message_logs=whatsapp_counts.message_logs,
        deleted_whatsapp_delivery_states=whatsapp_counts.delivery_states,
        storage_cleanup_deferred=bool(cleanup_jobs),
    )

    await AuditLogRepository(session).record(
        action="passport_data_purged",
        entity_type="platform" if current_user.role == UserRole.SUPER_ADMIN else "agency",
        agency_id=None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=None
        if current_user.role == UserRole.SUPER_ADMIN
        else str(current_user.agency_id),
        metadata={
            **response.model_dump(),
            "storage_objects_scheduled_for_cleanup": len(storage_keys),
            "storage_cleanup_job_count": len(cleanup_jobs),
            "request_fingerprint": mutation.request_fingerprint,
        },
        result="success",
    )

    # This explicit boundary is required because the FastAPI session dependency
    # otherwise commits only after the route returns. Cleanup may begin only
    # after the tombstones, row deletion, and audit event are durable together.
    try:
        await session.commit()
    except Exception as exc:
        await record_destructive_failure(
            mutation,
            user=current_user,
            error=exc,
        )
        raise

    cleanup_object_count = sum(job.object_count for job in cleanup_jobs)
    cleanup_deferred = cleanup_object_count > PASSPORT_PURGE_INLINE_CLEANUP_MAX_OBJECTS
    deleted_storage_objects = 0
    if not cleanup_deferred:
        for cleanup_job in cleanup_jobs:
            try:
                cleanup_result = await process_storage_cleanup_job(cleanup_job.id)
                if cleanup_result is None or not cleanup_result.completed:
                    cleanup_deferred = True
                    continue
                deleted_storage_objects += cleanup_result.deleted_count
            except Exception as exc:
                # The periodic lease-safe worker retries the already-committed
                # job; do not turn a completed database purge into an unsafe
                # compensating rollback.
                cleanup_deferred = True
                logger.warning(
                    "admin_passport_purge_storage_cleanup_deferred",
                    cleanup_job_id=str(cleanup_job.id),
                    object_count=cleanup_job.object_count,
                    error_type=type(exc).__name__,
                )

    response.deleted_storage_objects = deleted_storage_objects
    response.storage_cleanup_deferred = cleanup_deferred
    return response
