"""Durable manager removal followed by deferred object cleanup."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.destructive_mutation_policy import (
    DestructiveMutationPolicy,
    DestructiveOwnedGroupsMutation,
    record_destructive_failure,
)
from app.core.logging.logger import get_logger
from app.core.security.password import hash_password, run_password_work
from app.domain.entities.entities import (
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import (
    ClientGroupModel,
    NotificationModel,
    PassportProcessingJobModel,
    PassportSubmissionModel,
    StorageCleanupJobModel,
    UserModel,
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
from app.presentation.api.v1.routes.admin_account_scope import _manager_scope
from app.presentation.api.v1.routes.admin_deletion_queries import (
    _delete_by_ids,
    _delete_entity_rows,
)
from app.presentation.api.v1.routes.admin_manager_delete_replay import (
    _previous_manager_delete_result,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    DeleteManagerRequest,
    DeleteManagerResponse,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
logger = get_logger("app.presentation.api.v1.routes.admin")


@router.delete(
    "/managers/{manager_id}",
    response_model=DeleteManagerResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete a manager account",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def delete_manager(
    manager_id: uuid.UUID,
    body: DeleteManagerRequest | None = None,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> DeleteManagerResponse:
    delete_owned_data = bool(body and body.delete_owned_data)
    manager_result = await session.execute(
        select(UserModel)
        .where(UserModel.id == manager_id, *_manager_scope(current_user))
        .with_for_update()
    )
    manager = manager_result.scalar_one_or_none()
    if not manager:
        previous = await _previous_manager_delete_result(
            session,
            manager_id=manager_id,
            delete_owned_data=delete_owned_data,
        )
        if previous is not None:
            await AuditLogRepository(session).record(
                action="manager_delete_idempotent_replay",
                entity_type="user",
                entity_id=str(manager_id),
                agency_id=previous.agency_id,
                user_id=current_user.id,
                actor_email=current_user.email,
                metadata={
                    "delete_owned_data": delete_owned_data,
                    "result": "idempotent_replay",
                },
            )
            await session.commit()
            return previous.response
        raise EntityNotFoundError("Manager", manager_id)

    email_connection_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(EmailConnectionModel)
                .where(EmailConnectionModel.owner_user_id == manager.id)
            )
        ).scalar_one()
    )
    cleanup_jobs: tuple[StorageCleanupJobModel, ...] = ()
    owned_data_mutation: DestructiveOwnedGroupsMutation | None = None
    response = DeleteManagerResponse(
        deleted_manager_id=manager.id,
        deleted_owned_data=delete_owned_data,
    )

    if delete_owned_data:
        owned_data_mutation = await DestructiveMutationPolicy(session).require_manager_owned_groups(
            user=current_user,
            manager_id=manager.id,
            manager_agency_id=manager.agency_id,
            action="manager_owned_passport_data_delete",
        )
        group_ids = [group.id for group in owned_data_mutation.groups]

        submission_rows = (
            await session.execute(
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
                    PassportSubmissionModel.group_id.in_(group_ids),
                    PassportSubmissionModel.agency_id == manager.agency_id,
                )
                .with_for_update()
            )
            if group_ids
            else None
        )
        submissions = list(submission_rows.all()) if submission_rows else []
        submission_ids = [row.id for row in submissions]
        storage_keys = passport_storage_keys(submissions)
        crop_repository = PassportImageCropRepository(session)
        storage_keys.extend(await crop_repository.derived_storage_keys(submission_ids))
        storage_keys.extend(await crop_repository.edit_storage_keys(submission_ids))

        cleanup_jobs = stage_storage_cleanup_jobs(
            session,
            agency_id=manager.agency_id,
            source="passport_submission_delete",
            context_id=(f"manager:{manager.id}:{owned_data_mutation.request_fingerprint}"),
            storage_keys=storage_keys,
        )
        group_entity_ids = [str(group_id) for group_id in group_ids]
        submission_entity_ids = [str(submission_id) for submission_id in submission_ids]
        response.deleted_notifications = await _delete_entity_rows(
            session,
            NotificationModel,
            agency_id=manager.agency_id,
            group_entity_ids=group_entity_ids,
            submission_entity_ids=submission_entity_ids,
        )
        response.deleted_processing_jobs = await _delete_by_ids(
            session,
            PassportProcessingJobModel,
            PassportProcessingJobModel.submission_id,
            submission_ids,
        )
        response.deleted_passport_submissions = await _delete_by_ids(
            session,
            PassportSubmissionModel,
            PassportSubmissionModel.id,
            submission_ids,
        )
        response.deleted_client_groups = await _delete_by_ids(
            session, ClientGroupModel, ClientGroupModel.id, group_ids
        )

    await AuditLogRepository(session).record(
        action="manager_deleted",
        entity_type="user",
        entity_id=str(manager.id),
        agency_id=manager.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "delete_owned_data": delete_owned_data,
            "storage_cleanup_job_count": len(cleanup_jobs),
            **response.model_dump(mode="json"),
        },
    )
    if email_connection_count:
        now = datetime.now(tz=UTC)
        await session.execute(
            update(EmailConnectionModel)
            .where(EmailConnectionModel.owner_user_id == manager.id)
            .values(
                status="disconnected",
                sync_state="blocked",
                ai_processing_enabled=False,
                access_token_ciphertext=None,
                refresh_token_ciphertext=None,
                token_expires_at=None,
                sync_cursor=None,
                watch_resource_id=None,
                watch_expiration_at=None,
                sync_lease_token=None,
                sync_lease_expires_at=None,
                sync_generation=EmailConnectionModel.sync_generation + 1,
                next_sync_at=None,
                disconnected_at=now,
                last_error_code="EMAIL_OWNER_ACCOUNT_REMOVED",
                last_error_message="The mailbox owner account was removed.",
                last_error_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        manager.is_active = False
        manager.email = f"deleted-{manager.id}@deleted.invalid"
        manager.hashed_password = await run_password_work(hash_password, secrets.token_urlsafe(48))
        manager.deleted_at = now
        manager.updated_at = now
    else:
        await session.delete(manager)
    await session.flush()
    # The manager, owned passport rows, and encrypted object-cleanup tombstones
    # become durable together. Object storage is never touched before this
    # commit succeeds.
    try:
        await session.commit()
    except Exception as exc:
        if owned_data_mutation is not None:
            await record_destructive_failure(
                owned_data_mutation,
                user=current_user,
                error=exc,
            )
        raise

    for cleanup_job in cleanup_jobs:
        try:
            cleanup_result = await process_storage_cleanup_job(cleanup_job.id)
            if cleanup_result is None or not cleanup_result.completed:
                logger.warning(
                    "manager_passport_storage_cleanup_deferred",
                    manager_id=str(manager_id),
                    cleanup_job_id=str(cleanup_job.id),
                    object_count=cleanup_job.object_count,
                    error_type=None,
                )
                continue
            response.deleted_storage_objects += cleanup_result.deleted_count
        except Exception as exc:
            logger.warning(
                "manager_passport_storage_cleanup_deferred",
                manager_id=str(manager_id),
                cleanup_job_id=str(cleanup_job.id),
                object_count=cleanup_job.object_count,
                error_type=type(exc).__name__,
            )
    return response
