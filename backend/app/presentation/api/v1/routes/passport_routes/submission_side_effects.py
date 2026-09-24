"""Stage final-submission side effects in the caller's database transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.domain.entities.entities import PassportProcessingStatus
from app.domain.value_objects.passport_document_classification import requires_manual_staff_review
from app.infrastructure.database.models import StorageCleanupJobModel
from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel,
)
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs
from app.infrastructure.ecr.passport_runtime import stage_passport_ecr_check
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.notification_repository import NotificationRepository
from app.infrastructure.verification.job_repository import (
    PostSubmissionVerificationJob,
    PostSubmissionVerificationJobRepository,
)


@dataclass(frozen=True, slots=True)
class SubmissionSideEffects:
    verification_job: PostSubmissionVerificationJob | None
    cleanup_jobs: tuple[StorageCleanupJobModel, ...]
    ecr_queued: bool


async def stage_submission_side_effects(
    session: AsyncSession,
    *,
    result: PassportSubmissionOutputDTO,
    contact_proof: PublicUploadContactChallengeModel,
) -> SubmissionSideEffects:
    """Stage durable work without committing, publishing, or deleting objects."""
    # Proof consumption and submission promotion commit atomically. A failed
    # save leaves the verified proof usable; exact retries keep their proof.
    if not result.idempotent_replay:
        contact_proof.status = "consumed"
        contact_proof.consumed_at = datetime.now(UTC)
        contact_proof.updated_at = contact_proof.consumed_at
    verification_job = None
    if (
        result.image_s3_key
        and result.status == PassportProcessingStatus.SUBMITTED.value
        and not requires_manual_staff_review(result.post_submission_verification)
    ):
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
            sync_broadcast_contacts=True,
        )
        await AuditLogRepository(session).record(
            action="client_passport_submitted",
            entity_type="passport_submission",
            entity_id=str(result.id),
            agency_id=result.agency_id,
            metadata={
                "group_id": str(result.group_id),
                "submission_mode": result.submission_mode,
                "qualifier_enabled_snapshot": result.qualifier_enabled_snapshot,
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
    cleanup_jobs: tuple[StorageCleanupJobModel, ...] = ()
    if result.storage_cleanup_keys:
        cleanup_jobs = stage_storage_cleanup_jobs(
            session,
            agency_id=result.agency_id,
            source="passport_submission_delete",
            context_id=f"client-submit:{result.group_id}:{result.id}",
            storage_keys=result.storage_cleanup_keys,
        )
    ecr_queued = await stage_passport_ecr_check(session, result.id)
    return SubmissionSideEffects(verification_job, cleanup_jobs, ecr_queued)
