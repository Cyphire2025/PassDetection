"""Bounded cleanup for attendance-runtime, discard, and upload-security evidence."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings, get_settings
from app.infrastructure.database.models import (
    AttendanceCloseoutCheckpointModel,
    AttendanceDiscardTombstoneModel,
    AttendanceRecordModel,
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionRuntimeParticipantModel,
    UntrustedUploadScanModel,
)
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.upload_security import (
    QuarantineLocatorError,
    decrypt_quarantine_storage_key,
)

OPERATIONAL_RETENTION_BATCH_SIZE = 200


@dataclass(frozen=True, slots=True)
class OperationalRetentionResult:
    expired_runtimes: int
    deleted_runtime_registrations: int
    deleted_discard_tombstones: int
    deleted_upload_scan_records: int
    quarantine_cleanup_jobs: int
    quarantine_objects_scheduled: int
    quarantine_locator_failures: int

    def as_dict(self) -> dict[str, int]:
        return {
            "expired_runtimes": self.expired_runtimes,
            "deleted_runtime_registrations": self.deleted_runtime_registrations,
            "deleted_discard_tombstones": self.deleted_discard_tombstones,
            "deleted_upload_scan_records": self.deleted_upload_scan_records,
            "quarantine_cleanup_jobs": self.quarantine_cleanup_jobs,
            "quarantine_objects_scheduled": self.quarantine_objects_scheduled,
            "quarantine_locator_failures": self.quarantine_locator_failures,
        }


async def apply_operational_retention(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> OperationalRetentionResult:
    """Apply one restart-safe retention page in the caller transaction."""

    observed = now or datetime.now(tz=UTC)
    active = settings or get_settings()
    page_size = min(
        OPERATIONAL_RETENTION_BATCH_SIZE,
        active.attendance_discard_batch_size,
    )

    expiring_runtime_ids = (
        select(AttendanceRuntimeRegistrationModel.id)
        .where(
            AttendanceRuntimeRegistrationModel.status == "active",
            AttendanceRuntimeRegistrationModel.expires_at <= observed,
        )
        .order_by(
            AttendanceRuntimeRegistrationModel.expires_at,
            AttendanceRuntimeRegistrationModel.id,
        )
        .limit(page_size)
        .with_for_update(skip_locked=True)
    )
    expired_result = await session.execute(
        update(AttendanceRuntimeRegistrationModel)
        .where(AttendanceRuntimeRegistrationModel.id.in_(expiring_runtime_ids))
        .values(
            status="expired",
            revoked_at=observed,
            revoke_reason="registration_expired",
            updated_at=observed,
        )
        .execution_options(synchronize_session=False)
    )
    expired_runtimes = int(getattr(expired_result, "rowcount", 0) or 0)

    expired_discard_ids = (
        select(AttendanceDiscardTombstoneModel.id)
        .where(AttendanceDiscardTombstoneModel.retention_expires_at <= observed)
        .order_by(
            AttendanceDiscardTombstoneModel.retention_expires_at,
            AttendanceDiscardTombstoneModel.id,
        )
        .limit(page_size)
        .with_for_update(skip_locked=True)
    )
    discard_result = await session.execute(
        delete(AttendanceDiscardTombstoneModel).where(
            AttendanceDiscardTombstoneModel.id.in_(expired_discard_ids)
        )
    )
    deleted_discard_tombstones = int(getattr(discard_result, "rowcount", 0) or 0)

    upload_rows = list(
        (
            await session.execute(
                select(UntrustedUploadScanModel)
                .where(UntrustedUploadScanModel.retention_expires_at <= observed)
                .order_by(
                    UntrustedUploadScanModel.retention_expires_at,
                    UntrustedUploadScanModel.id,
                )
                .limit(OPERATIONAL_RETENTION_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    deletable_upload_ids: list[uuid.UUID] = []
    quarantine_by_agency: dict[uuid.UUID | None, list[tuple[uuid.UUID, str]]] = defaultdict(list)
    locator_failures = 0
    for row in upload_rows:
        if row.disposition != "quarantined":
            deletable_upload_ids.append(row.id)
            continue
        if row.quarantine_key_ciphertext is None or row.quarantine_key_version is None:
            locator_failures += 1
            continue
        try:
            storage_key = decrypt_quarantine_storage_key(
                settings=active,
                ciphertext=row.quarantine_key_ciphertext,
                key_version=row.quarantine_key_version,
            )
        except QuarantineLocatorError:
            locator_failures += 1
            row.error_code = "QUARANTINE_LOCATOR_INVALID"
            continue
        quarantine_by_agency[row.agency_id].append((row.id, storage_key))

    cleanup_jobs = 0
    cleanup_objects = 0
    for agency_id, retained in quarantine_by_agency.items():
        row_ids = [row_id for row_id, _ in retained]
        jobs = stage_storage_cleanup_jobs(
            session,
            agency_id=agency_id,
            source="untrusted_upload_quarantine",
            context_id="upload-retention:" + ",".join(str(row_id) for row_id in row_ids),
            storage_keys=[key for _, key in retained],
            now=observed,
        )
        cleanup_jobs += len(jobs)
        cleanup_objects += sum(job.object_count for job in jobs)
        deletable_upload_ids.extend(row_ids)

    deleted_upload_scan_records = 0
    if deletable_upload_ids:
        upload_delete = await session.execute(
            delete(UntrustedUploadScanModel).where(
                UntrustedUploadScanModel.id.in_(deletable_upload_ids)
            )
        )
        deleted_upload_scan_records = int(getattr(upload_delete, "rowcount", 0) or 0)

    runtime_cutoff = observed - timedelta(days=active.attendance_runtime_retention_days)
    referenced_runtime = (
        select(AttendanceSessionRuntimeParticipantModel.id)
        .where(
            AttendanceSessionRuntimeParticipantModel.runtime_registration_id
            == AttendanceRuntimeRegistrationModel.id
        )
        .exists()
    )
    checkpoint_runtime = (
        select(AttendanceCloseoutCheckpointModel.id)
        .where(
            AttendanceCloseoutCheckpointModel.runtime_registration_id
            == AttendanceRuntimeRegistrationModel.id
        )
        .exists()
    )
    attendance_runtime = (
        select(AttendanceRecordModel.id)
        .where(
            AttendanceRecordModel.runtime_registration_id == AttendanceRuntimeRegistrationModel.id
        )
        .exists()
    )
    discard_runtime = (
        select(AttendanceDiscardTombstoneModel.id)
        .where(
            AttendanceDiscardTombstoneModel.runtime_registration_id
            == AttendanceRuntimeRegistrationModel.id
        )
        .exists()
    )
    terminal_runtime_ids = (
        select(AttendanceRuntimeRegistrationModel.id)
        .where(
            AttendanceRuntimeRegistrationModel.status != "active",
            func.coalesce(
                AttendanceRuntimeRegistrationModel.revoked_at,
                AttendanceRuntimeRegistrationModel.expires_at,
            )
            <= runtime_cutoff,
            ~referenced_runtime,
            ~checkpoint_runtime,
            ~attendance_runtime,
            ~discard_runtime,
        )
        .order_by(
            func.coalesce(
                AttendanceRuntimeRegistrationModel.revoked_at,
                AttendanceRuntimeRegistrationModel.expires_at,
            ),
            AttendanceRuntimeRegistrationModel.id,
        )
        .limit(page_size)
        .with_for_update(skip_locked=True)
    )
    runtime_delete = await session.execute(
        delete(AttendanceRuntimeRegistrationModel).where(
            AttendanceRuntimeRegistrationModel.id.in_(terminal_runtime_ids)
        )
    )
    deleted_runtime_registrations = int(getattr(runtime_delete, "rowcount", 0) or 0)

    result = OperationalRetentionResult(
        expired_runtimes=expired_runtimes,
        deleted_runtime_registrations=deleted_runtime_registrations,
        deleted_discard_tombstones=deleted_discard_tombstones,
        deleted_upload_scan_records=deleted_upload_scan_records,
        quarantine_cleanup_jobs=cleanup_jobs,
        quarantine_objects_scheduled=cleanup_objects,
        quarantine_locator_failures=locator_failures,
    )
    if any(result.as_dict().values()):
        await AuditLogRepository(session).record(
            action="operational_retention_applied",
            entity_type="retention_policy",
            entity_id="attendance-and-upload-security",
            metadata=result.as_dict(),
        )
    metrics.increment("operational_retention.runs")
    for name, value in result.as_dict().items():
        metrics.increment(f"operational_retention.{name}", value)
    await session.flush()
    return result


__all__ = [
    "OPERATIONAL_RETENTION_BATCH_SIZE",
    "OperationalRetentionResult",
    "apply_operational_retention",
]
