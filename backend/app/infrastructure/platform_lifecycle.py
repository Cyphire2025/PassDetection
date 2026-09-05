"""Bounded enforcement of administrator-configured lifecycle policies."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClientGroupModel,
    NotificationModel,
    PassportSubmissionModel,
)
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.repositories.platform_policy_repository import (
    PlatformPolicyRepository,
)
from app.infrastructure.storage.passport_object_keys import passport_storage_keys

LIFECYCLE_GROUP_BATCH_SIZE = 1_000
LIFECYCLE_PASSPORT_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class PlatformLifecycleResult:
    archived_groups: int
    scheduled_passport_purge_dates: int
    deleted_passports: int
    deleted_notifications: int
    deleted_audit_logs: int
    storage_cleanup_jobs: int
    storage_objects_scheduled: int

    def as_dict(self) -> dict[str, int]:
        return {
            "archived_groups": self.archived_groups,
            "scheduled_passport_purge_dates": self.scheduled_passport_purge_dates,
            "deleted_passports": self.deleted_passports,
            "deleted_notifications": self.deleted_notifications,
            "deleted_audit_logs": self.deleted_audit_logs,
            "storage_cleanup_jobs": self.storage_cleanup_jobs,
            "storage_objects_scheduled": self.storage_objects_scheduled,
        }


async def apply_platform_lifecycle_policies(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> PlatformLifecycleResult:
    """Apply one idempotent, bounded lifecycle page in the caller transaction.

    Passport age is measured from group closure/deletion, never upload time.
    Active groups are therefore outside the destructive retention boundary.
    Storage tombstones are staged before database rows are removed and share
    the same commit, while object deletion remains an after-commit worker job.
    """

    timestamp = now or datetime.now(tz=UTC)
    policies = await PlatformPolicyRepository(session).load()
    archive_cutoff = timestamp - timedelta(
        days=policies.auto_archive_closed_groups_days
    )

    archive_group_ids = (
        select(ClientGroupModel.id)
        .where(
            ClientGroupModel.status == "closed",
            ClientGroupModel.closed_at.is_not(None),
            ClientGroupModel.closed_at <= archive_cutoff,
        )
        .order_by(ClientGroupModel.closed_at, ClientGroupModel.id)
        .limit(LIFECYCLE_GROUP_BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    archived = await session.execute(
        update(ClientGroupModel)
        .where(
            ClientGroupModel.id.in_(archive_group_ids),
        )
        .values(status="archived")
        .execution_options(synchronize_session=False)
    )
    archived_count = int(getattr(archived, "rowcount", 0) or 0)

    retention_anchor = func.coalesce(
        ClientGroupModel.deleted_at,
        ClientGroupModel.closed_at,
    )
    unscheduled_result = await session.execute(
        select(ClientGroupModel)
        .where(
            ClientGroupModel.status.in_(("closed", "archived", "deleted")),
            retention_anchor.is_not(None),
            or_(
                ClientGroupModel.passport_purge_at.is_(None),
                ClientGroupModel.passport_retention_days_applied.is_distinct_from(
                    policies.passport_data_retention_days
                ),
            ),
        )
        .order_by(retention_anchor, ClientGroupModel.id)
        .limit(LIFECYCLE_GROUP_BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    unscheduled_groups = list(unscheduled_result.scalars().all())
    for group in unscheduled_groups:
        anchor = group.deleted_at or group.closed_at
        if anchor is not None:
            group.passport_purge_at = anchor + timedelta(
                days=policies.passport_data_retention_days
            )
            group.passport_retention_days_applied = (
                policies.passport_data_retention_days
            )

    submissions_result = await session.execute(
        select(
            PassportSubmissionModel.id,
            PassportSubmissionModel.agency_id,
            PassportSubmissionModel.image_s3_key,
            PassportSubmissionModel.thumbnail_s3_key,
            PassportSubmissionModel.passport_back_s3_key,
            PassportSubmissionModel.passport_cover_s3_key,
            PassportSubmissionModel.passport_back_cover_s3_key,
            PassportSubmissionModel.passport_photo_s3_key,
        )
        .join(ClientGroupModel, ClientGroupModel.id == PassportSubmissionModel.group_id)
        .where(
            ClientGroupModel.status.in_(("closed", "archived", "deleted")),
            ClientGroupModel.passport_purge_at.is_not(None),
            ClientGroupModel.passport_purge_at <= timestamp,
            ClientGroupModel.passport_legal_hold.is_(False),
        )
        .order_by(ClientGroupModel.passport_purge_at, PassportSubmissionModel.id)
        .limit(LIFECYCLE_PASSPORT_BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    submissions = list(submissions_result.all())

    submissions_by_agency: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for submission in submissions:
        submissions_by_agency[submission.agency_id].append(submission)

    cleanup_job_count = 0
    storage_object_count = 0
    crop_repository = PassportImageCropRepository(session)
    for agency_id, agency_submissions in submissions_by_agency.items():
        submission_ids = [submission.id for submission in agency_submissions]
        storage_keys = passport_storage_keys(agency_submissions)
        storage_keys.extend(
            await crop_repository.derived_storage_keys(submission_ids)
        )
        storage_keys.extend(await crop_repository.edit_storage_keys(submission_ids))
        cleanup_jobs = stage_storage_cleanup_jobs(
            session,
            agency_id=agency_id,
            source="passport_submission_delete",
            context_id=(
                f"retention:{timestamp.date().isoformat()}:{agency_id}:"
                + ",".join(str(item) for item in sorted(submission_ids, key=str))
            ),
            storage_keys=storage_keys,
        )
        cleanup_job_count += len(cleanup_jobs)
        storage_object_count += sum(job.object_count for job in cleanup_jobs)

    submission_ids = [submission.id for submission in submissions]
    submission_entity_ids = [str(submission_id) for submission_id in submission_ids]
    deleted_notifications_count = 0
    deleted_passports_count = 0
    if submission_ids:
        notifications = await session.execute(
            delete(NotificationModel).where(
                NotificationModel.entity_type == "passport_submission",
                NotificationModel.entity_id.in_(submission_entity_ids),
            )
        )
        deleted_notifications_count = int(
            getattr(notifications, "rowcount", 0) or 0
        )
        deleted_passports = await session.execute(
            delete(PassportSubmissionModel).where(
                PassportSubmissionModel.id.in_(submission_ids)
            )
        )
        deleted_passports_count = int(
            getattr(deleted_passports, "rowcount", 0) or 0
        )
        if deleted_passports_count != len(submission_ids):
            raise RuntimeError("Passport retention page changed while locked")

    result = PlatformLifecycleResult(
        archived_groups=archived_count,
        scheduled_passport_purge_dates=len(unscheduled_groups),
        deleted_passports=deleted_passports_count,
        deleted_notifications=deleted_notifications_count,
        # Audit rows are application-append-only as of schema 0087. The policy
        # value remains an external archival/WORM minimum, not permission for
        # the ordinary application role to erase local security evidence.
        deleted_audit_logs=0,
        storage_cleanup_jobs=cleanup_job_count,
        storage_objects_scheduled=storage_object_count,
    )
    if any(result.as_dict().values()):
        await AuditLogRepository(session).record(
            action="platform_lifecycle_policies_applied",
            entity_type="platform_settings",
            entity_id="global",
            metadata=result.as_dict(),
        )
    await session.flush()
    return result
