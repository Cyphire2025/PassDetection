"""Bulk passport delete: focused scope, mutation or transaction owner."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.destructive_mutation_policy import (
    DestructiveMutationPolicy,
    record_destructive_failure,
)
from app.domain.entities.entities import (
    User,
)
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.models import (
    NotificationModel,
    PassportSubmissionModel,
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
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    lock_linked_whatsapp_broadcast_groups,
)
from app.infrastructure.storage.passport_object_keys import passport_storage_keys
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    prepare_private_delivery_identity_mutation,
)
from app.presentation.api.v1.routes.passport_deletion_support import previous_bulk_delete_result
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkDeletePassportSubmissionsRequest,
    BulkDeletePassportSubmissionsResponse,
)
from app.presentation.dependencies.auth import require_recent_mfa
from app.presentation.dependencies.csrf import require_cookie_csrf

from .bulk_actions_roster import _active_roster_resolution_references, logger
from .constants import PASSPORT_DELETE_INLINE_CLEANUP_MAX_OBJECTS

router = APIRouter()


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
    current_user: User = Depends(require_recent_mfa),
    session: AsyncSession = Depends(get_db_session),
) -> BulkDeletePassportSubmissionsResponse:
    submission_ids = list(dict.fromkeys(body.submission_ids))
    destructive_policy = DestructiveMutationPolicy(session)
    mutation = await destructive_policy.require_group(
        user=current_user,
        group_id=group_id,
        action="passport_submissions_bulk_delete",
        target_ids=submission_ids,
        delete_scope="submissions",
    )
    group = mutation.group
    await lock_linked_whatsapp_broadcast_groups(
        session,
        agency_id=group.agency_id,
        group_id=group_id,
    )
    selected_rows = await session.execute(
        select(
            PassportSubmissionModel.id,
            PassportSubmissionModel.image_s3_key,
            PassportSubmissionModel.thumbnail_s3_key,
            PassportSubmissionModel.passport_back_s3_key,
            PassportSubmissionModel.passport_cover_s3_key,
            PassportSubmissionModel.passport_back_cover_s3_key,
            PassportSubmissionModel.passport_photo_s3_key,
        )
        .where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.id.in_(submission_ids),
        )
        .with_for_update()
    )
    submissions = list(selected_rows.all())
    found_ids = {row.id for row in submissions}
    missing_ids = [
        submission_id for submission_id in submission_ids if submission_id not in found_ids
    ]
    if missing_ids:
        previous_result = await previous_bulk_delete_result(
            session,
            group_id=group_id,
            request_fingerprint=mutation.request_fingerprint,
            requested_submission_ids=submission_ids,
        )
        if previous_result is not None:
            await AuditLogRepository(session).record(
                action="passport_submissions_bulk_delete_idempotent_replay",
                entity_type="client_group",
                entity_id=str(group_id),
                agency_id=group.agency_id,
                user_id=current_user.id,
                actor_email=current_user.email,
                metadata={
                    "request_fingerprint": mutation.request_fingerprint,
                    "target_count": len(submission_ids),
                },
            )
            await session.commit()
            return previous_result
        await destructive_policy.block_group(
            mutation,
            user=current_user,
            error=ConflictError(
                "One or more selected passport submissions were not found "
                "in this group. Refresh the page and try again.",
                code="PASSPORT_DELETE_SELECTION_STALE",
            ),
        )

    # Replacement creation locks its submission before recording a roster
    # decision. Taking the same locks first closes the check/delete race: either
    # the decision commits first and is observed below, or it waits and then
    # finds that the submission no longer exists.
    protected_submission_ids = await _active_roster_resolution_references(
        session,
        group_id=group_id,
        agency_id=group.agency_id,
    )
    selected_protected_ids = protected_submission_ids.intersection(submission_ids)
    if selected_protected_ids:
        await destructive_policy.block_group(
            mutation,
            user=current_user,
            error=ConflictError(
                "One or more selected uploads belong to an active "
                "replacement or rejection. Restore that roster decision "
                "before permanently deleting the upload.",
                code="PASSPORT_ROSTER_DECISION_ACTIVE",
            ),
        )

    try:
        await prepare_private_delivery_identity_mutation(
            session,
            agency_id=group.agency_id,
            group_id=group_id,
            cancel_queued=True,
            cancellation_reason="Passenger removed before private WhatsApp delivery.",
        )
    except PrivateDeliveryMutationBlocked as exc:
        raise ConflictError(str(exc), code="WHATSAPP_SOURCE_SYNC_DELIVERY_ACTIVE") from exc

    storage_keys = passport_storage_keys(submissions)
    crop_repository = PassportImageCropRepository(session)
    storage_keys.extend(await crop_repository.derived_storage_keys(submission_ids))
    storage_keys.extend(await crop_repository.edit_storage_keys(submission_ids))
    cleanup_jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=group.agency_id,
        source="passport_submission_delete",
        context_id=(
            f"{group_id}:" + ",".join(str(item) for item in sorted(submission_ids, key=str))
        ),
        storage_keys=storage_keys,
    )
    notification_result = await session.execute(
        delete(NotificationModel).where(
            NotificationModel.agency_id == group.agency_id,
            NotificationModel.entity_type == "passport_submission",
            NotificationModel.entity_id.in_(
                [str(submission_id) for submission_id in submission_ids]
            ),
        )
    )
    deleted_notifications = int(getattr(notification_result, "rowcount", 0) or 0)
    from app.application.travellers.retention import detach_submission_provenance

    await detach_submission_provenance(session, submission_ids)
    delete_result = await session.execute(
        delete(PassportSubmissionModel).where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.id.in_(submission_ids),
        )
    )
    deleted_count = int(getattr(delete_result, "rowcount", 0) or 0)
    if deleted_count != len(submission_ids):
        raise ConflictError(
            (
                "The selected submissions changed while deletion was in "
                "progress. Refresh the page and try again."
            ),
            code="PASSPORT_DELETE_CONCURRENT_CHANGE",
        )

    await propagate_mobile_passenger_change(
        session,
        agency_id=group.agency_id,
        group_id=group_id,
        passenger_submission_ids=submission_ids,
        actor_user_id=current_user.id,
        operation="delete",
        change_kind="documents",
        sync_broadcast_contacts=True,
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
            "deleted_submission_ids": [str(submission_id) for submission_id in submission_ids],
            "storage_objects_scheduled_for_cleanup": len(storage_keys),
            "storage_cleanup_job_count": len(cleanup_jobs),
            "deleted_notifications": deleted_notifications,
            "request_fingerprint": mutation.request_fingerprint,
        },
    )
    # Commit the authoritative database deletion before touching object
    # storage. A failed commit therefore leaves every passport file intact.
    try:
        await session.commit()
    except Exception as exc:
        await record_destructive_failure(
            mutation,
            user=current_user,
            error=exc,
        )
        raise

    deleted_storage_objects = 0
    cleanup_object_count = sum(job.object_count for job in cleanup_jobs)
    # Keep the request path responsive for large deletions. The committed,
    # encrypted cleanup jobs are picked up by the periodic worker; small jobs
    # still get an immediate best-effort pass for prompt object removal.
    storage_cleanup_deferred = cleanup_object_count > PASSPORT_DELETE_INLINE_CLEANUP_MAX_OBJECTS
    if not storage_cleanup_deferred:
        for cleanup_job in cleanup_jobs:
            try:
                cleanup_result = await process_storage_cleanup_job(cleanup_job.id)
                if cleanup_result is None or not cleanup_result.completed:
                    storage_cleanup_deferred = True
                    continue
                deleted_storage_objects += cleanup_result.deleted_count
            except Exception as exc:
                # The database deletion and encrypted retry job are already
                # committed. The periodic worker will safely resume this cleanup.
                storage_cleanup_deferred = True
                logger.warning(
                    "passport_bulk_delete_storage_cleanup_deferred",
                    cleanup_job_id=str(cleanup_job.id),
                    group_id=str(group_id),
                    submission_count=deleted_count,
                    object_count=cleanup_job.object_count,
                    error_type=type(exc).__name__,
                )

    return BulkDeletePassportSubmissionsResponse(
        deleted_count=deleted_count,
        deleted_submission_ids=submission_ids,
        deleted_storage_objects=deleted_storage_objects,
        deleted_notifications=deleted_notifications,
        storage_cleanup_deferred=storage_cleanup_deferred,
    )


bulk_delete_passport_submissions.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.bulk_actions"
)
