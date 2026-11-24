"""Bulk passport transitions: focused scope, mutation or transaction owner."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import NamedTuple

from app.domain.entities.entities import (
    PassportProcessingStatus,
    StaffApprovalOutcome,
    User,
)
from app.infrastructure.database.models import (
    AuditLogModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkStaffApproveSkippedSubmission,
)


class _BulkApprovalChanges(NamedTuple):
    approved_ids: list[uuid.UUID]
    already_approved_ids: list[uuid.UUID]
    skipped: list[BulkStaffApproveSkippedSubmission]
    audit_rows: list[AuditLogModel]


def _apply_bulk_staff_approvals(
    models: list[PassportSubmissionModel],
    *,
    selection_by_id: dict[uuid.UUID, int],
    actor: User,
    group_id: uuid.UUID,
) -> _BulkApprovalChanges:
    approvable_statuses = {
        PassportProcessingStatus.CONFIRMED.value,
        PassportProcessingStatus.CLIENT_SUBMITTED.value,
        PassportProcessingStatus.SUBMITTED.value,
        PassportProcessingStatus.AI_APPROVED.value,
        PassportProcessingStatus.NEEDS_REVIEW.value,
        PassportProcessingStatus.STAFF_APPROVED.value,
    }
    approved_ids: list[uuid.UUID] = []
    already_approved_ids: list[uuid.UUID] = []
    skipped: list[BulkStaffApproveSkippedSubmission] = []
    audit_rows: list[AuditLogModel] = []
    now = datetime.now(tz=UTC)

    for model in models:
        expected_revision = selection_by_id[model.id]
        if model.status == PassportProcessingStatus.STAFF_APPROVED.value:
            already_approved_ids.append(model.id)
            continue
        if model.status not in approvable_statuses:
            skipped.append(
                BulkStaffApproveSkippedSubmission(
                    submission_id=model.id,
                    current_status=model.status,
                    reason="not_completed",
                    expected_extraction_revision=expected_revision,
                    current_extraction_revision=model.extraction_revision,
                )
            )
            continue
        if model.extraction_revision != expected_revision:
            skipped.append(
                BulkStaffApproveSkippedSubmission(
                    submission_id=model.id,
                    current_status=model.status,
                    reason="stale",
                    expected_extraction_revision=expected_revision,
                    current_extraction_revision=model.extraction_revision,
                )
            )
            continue

        entity = PassportSubmissionRepository._to_entity(model)
        prior_status = entity.status.value
        outcome = entity.bulk_staff_approve_completed_verification(
            reviewer_id=actor.id,
            reviewer_name=actor.full_name,
        )
        if outcome is StaffApprovalOutcome.ALREADY_APPROVED:  # pragma: no cover
            already_approved_ids.append(model.id)
            continue

        model.status = entity.status.value
        model.extraction_revision = entity.extraction_revision
        model.post_submission_verification_revision = entity.post_submission_verification_revision
        model.verification_reviewed_by_user_id = entity.verification_reviewed_by_user_id
        model.verification_reviewer_name = entity.verification_reviewer_name
        model.verification_reviewed_at = entity.verification_reviewed_at
        model.confirmed_at = entity.confirmed_at
        model.updated_at = entity.updated_at
        approved_ids.append(model.id)
        audit_rows.append(
            AuditLogModel(
                id=uuid.uuid4(),
                agency_id=model.agency_id,
                user_id=actor.id,
                actor_email=actor.email,
                action="passport_staff_approved",
                entity_type="passport_submission",
                entity_id=str(model.id),
                metadata_json={
                    "group_id": str(group_id),
                    "prior_status": prior_status,
                    "new_status": PassportProcessingStatus.STAFF_APPROVED.value,
                    "outcome": StaffApprovalOutcome.APPROVED.value,
                    "bulk": True,
                    "extraction_revision": entity.extraction_revision,
                    "verification_revision": (entity.post_submission_verification_revision),
                },
                created_at=now,
            )
        )
    return _BulkApprovalChanges(approved_ids, already_approved_ids, skipped, audit_rows)
