"""Permanent Delete for upload links; HTTP declarations remain in client_groups."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.application.security.destructive_mutation_policy import (
    DestructiveMutationPolicy,
)
from app.application.travellers.retention import detach_submission_provenance
from app.domain.entities.entities import (
    User,
)
from app.domain.exceptions.exceptions import (
    ConflictError,
)
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    ManagerGroupAccessModel,
    NotificationModel,
    PassportProcessingJobModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    QualifierSelectionModel,
    StorageCleanupJobModel,
)
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepositoryType,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.repositories.platform_policy_repository import PlatformPolicyRepository
from app.infrastructure.storage.passport_object_keys import passport_storage_keys
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
)
from app.presentation.api.v1.routes.client_group_operation_dependencies import (
    LockLinkedWhatsappBroadcastGroups,
    PreparePrivateDeliveryIdentityMutation,
    RecordDestructiveFailure,
    StageStorageCleanupJobs,
    SyncGroupBroadcastContacts,
)


async def permanently_delete_client_group(
    link_id: uuid.UUID,
    retain_records: bool,
    current_user: User,
    session: AsyncSession,
    *,
    lock_linked_whatsapp_broadcast_groups: LockLinkedWhatsappBroadcastGroups,
    prepare_private_delivery_identity_mutation: PreparePrivateDeliveryIdentityMutation,
    record_destructive_failure: RecordDestructiveFailure,
    stage_storage_cleanup_jobs: StageStorageCleanupJobs,
    sync_group_broadcast_contacts: SyncGroupBroadcastContacts,
    AuditLogRepository: type[AuditLogRepositoryType],
) -> dict[str, int | bool]:
    repo = ClientGroupRepository(session)
    destructive_policy = DestructiveMutationPolicy(session)
    mutation = await destructive_policy.require_group(
        user=current_user,
        group_id=link_id,
        action="client_group_permanent_delete",
    )
    group = mutation.group
    if group.status.value == "deleted":
        if group.deletion_retained_records != retain_records:
            await destructive_policy.block_group(
                mutation,
                user=current_user,
                error=ConflictError(
                    "This group was already deleted with a different retention policy.",
                    code="DESTRUCTIVE_REQUEST_CONFLICT",
                ),
            )
        await AuditLogRepository(session).record(
            action="client_group_permanent_delete_idempotent_replay",
            entity_type="client_group",
            entity_id=str(link_id),
            agency_id=group.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "retained_records": retain_records,
                "request_fingerprint": mutation.request_fingerprint,
            },
        )
        await session.commit()
        return {
            "deleted": True,
            "retained_records": retain_records,
            "historical_passport_count": group.deleted_passport_count,
            "deleted_passport_submissions": 0,
            "deleted_processing_jobs": 0,
            "deleted_qualifier_selections": 0,
            "deleted_storage_objects": 0,
            "storage_cleanup_deferred": not retain_records,
        }
    if group.status.value != "archived":
        await destructive_policy.block_group(
            mutation,
            user=current_user,
            error=ConflictError(
                "Archive the group before permanent deletion",
                code="GROUP_ARCHIVE_REQUIRED",
            ),
        )

    active_resolution_result = await session.execute(
        select(PassportRosterResolutionModel.id)
        .where(
            PassportRosterResolutionModel.client_group_id == link_id,
            PassportRosterResolutionModel.agency_id == group.agency_id,
            PassportRosterResolutionModel.status == "active",
        )
        .limit(1)
    )
    if active_resolution_result.scalar_one_or_none() is not None:
        await destructive_policy.block_group(
            mutation,
            user=current_user,
            error=ConflictError(
                "Restore all active replacement and rejection decisions "
                "before permanently deleting this group.",
                code="PASSPORT_ROSTER_DECISION_ACTIVE",
            ),
        )

    await lock_linked_whatsapp_broadcast_groups(
        session,
        agency_id=group.agency_id,
        group_id=link_id,
    )
    try:
        await prepare_private_delivery_identity_mutation(
            session,
            agency_id=group.agency_id,
            group_id=link_id,
            cancel_queued=True,
            cancellation_reason="Source group deleted before private WhatsApp delivery.",
        )
    except PrivateDeliveryMutationBlocked as exc:
        raise ConflictError(str(exc), code="WHATSAPP_SOURCE_SYNC_DELIVERY_ACTIVE") from exc

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
        .where(
            PassportSubmissionModel.group_id == link_id,
            PassportSubmissionModel.agency_id == group.agency_id,
        )
        .with_for_update()
    )
    submissions = list(submission_rows.all())
    submission_ids = [row.id for row in submissions]
    storage_keys = passport_storage_keys(submissions)
    crop_repository = PassportImageCropRepository(session)
    storage_keys.extend(await crop_repository.derived_storage_keys(submission_ids))
    storage_keys.extend(await crop_repository.edit_storage_keys(submission_ids))

    await session.execute(
        delete(ManagerGroupAccessModel).where(ManagerGroupAccessModel.group_id == link_id)
    )
    affected_broadcast_ids = tuple(
        (
            await session.scalars(
                select(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id).where(
                    ClientGroupWhatsAppBroadcastLinkModel.client_group_id == link_id,
                    ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
                    ClientGroupWhatsAppBroadcastLinkModel.sync_contacts_from_group.is_(True),
                )
            )
        ).all()
    )
    await session.execute(
        delete(ClientGroupWhatsAppBroadcastLinkModel).where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == link_id
        )
    )
    deleted_storage_objects = 0
    deleted_processing_jobs = 0
    deleted_passport_submissions = 0
    deleted_qualifier_selections = 0
    cleanup_jobs: tuple[StorageCleanupJobModel, ...] = ()
    if not retain_records:
        await detach_submission_provenance(session, submission_ids)
        cleanup_jobs = stage_storage_cleanup_jobs(
            session,
            agency_id=group.agency_id,
            source="passport_submission_delete",
            context_id=f"group:{link_id}",
            storage_keys=storage_keys,
        )
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
        qualifier_result = await session.execute(
            delete(QualifierSelectionModel).where(QualifierSelectionModel.group_id == link_id)
        )
        deleted_qualifier_selections = int(getattr(qualifier_result, "rowcount", 0) or 0)
    await session.execute(
        delete(NotificationModel).where(
            NotificationModel.agency_id == group.agency_id,
            NotificationModel.entity_type == "client_group",
            NotificationModel.entity_id == str(link_id),
        )
    )
    policies = await PlatformPolicyRepository(session).load()
    group.mark_deleted(
        passport_count=len(submissions),
        retain_records=retain_records,
        passport_retention_days=policies.passport_data_retention_days,
    )
    await repo.update(group)
    await sync_group_broadcast_contacts(
        session,
        agency_id=group.agency_id,
        group_id=group.id,
        actor_user_id=current_user.id,
        affected_broadcast_ids=affected_broadcast_ids,
    )
    await AuditLogRepository(session).record(
        action="client_group_deleted_with_retention"
        if retain_records
        else "client_group_deleted_with_data_removal",
        entity_type="client_group",
        entity_id=str(link_id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "group_name": group.name,
            "retained_records": retain_records,
            "historical_passport_count": len(submissions),
            "deleted_passport_submissions": deleted_passport_submissions,
            "deleted_processing_jobs": deleted_processing_jobs,
            "deleted_qualifier_selections": deleted_qualifier_selections,
            "deleted_storage_objects": deleted_storage_objects,
            "storage_objects_scheduled_for_cleanup": len(storage_keys) if not retain_records else 0,
            "storage_cleanup_job_count": len(cleanup_jobs),
            "request_fingerprint": mutation.request_fingerprint,
            "passport_purge_at": (
                group.passport_purge_at.isoformat() if group.passport_purge_at is not None else None
            ),
        },
    )
    try:
        await session.commit()
    except Exception as exc:
        await record_destructive_failure(
            mutation,
            user=current_user,
            error=exc,
        )
        raise
    return {
        "deleted": True,
        "retained_records": retain_records,
        "historical_passport_count": len(submissions),
        "deleted_passport_submissions": deleted_passport_submissions,
        "deleted_processing_jobs": deleted_processing_jobs,
        "deleted_qualifier_selections": deleted_qualifier_selections,
        "deleted_storage_objects": deleted_storage_objects,
        "storage_cleanup_deferred": bool(cleanup_jobs),
    }


async def _delete_by_ids(
    session: AsyncSession,
    model: type[PassportProcessingJobModel] | type[PassportSubmissionModel],
    column: InstrumentedAttribute[uuid.UUID],
    ids: list[uuid.UUID],
) -> int:
    if not ids:
        return 0
    result = await session.execute(delete(model).where(column.in_(ids)))
    return int(result.rowcount or 0)
