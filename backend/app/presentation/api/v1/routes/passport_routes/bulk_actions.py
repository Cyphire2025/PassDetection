"""Passport bulk actions: focused workflow boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.security.destructive_mutation_policy import (
    DestructiveMutationPolicy,
    record_destructive_failure,
)
from app.core.logging.logger import get_logger
from app.domain.entities.entities import (
    GroupStatus,
    PassportProcessingStatus,
    StaffApprovalOutcome,
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.models import (
    AuditLogModel,
    ClientGroupModel,
    NotificationModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.storage_cleanup import (
    process_storage_cleanup_job,
    stage_storage_cleanup_jobs,
)
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)
from app.infrastructure.qr.approved_passenger_qr_issuer import ensure_approved_passenger_qrs
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.storage.passport_object_keys import passport_storage_keys
from app.presentation.api.v1.routes.passport_deletion_support import previous_bulk_delete_result
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkDeletePassportSubmissionsRequest,
    BulkDeletePassportSubmissionsResponse,
    BulkStaffApprovePassportSubmissionsRequest,
    BulkStaffApprovePassportSubmissionsResponse,
    BulkStaffApproveSkippedSubmission,
)
from app.presentation.dependencies.auth import get_current_active_user, require_recent_mfa
from app.presentation.dependencies.csrf import require_cookie_csrf

from .constants import PASSPORT_DELETE_INLINE_CLEANUP_MAX_OBJECTS

router = APIRouter()

logger = get_logger(__name__)


async def _lock_active_bulk_approval_actor(
    session: AsyncSession,
    current_user: User,
) -> User:
    """Revalidate the unchanged bulk-approval actor under a row lock."""

    agency_filter = (
        UserModel.agency_id.is_(None)
        if current_user.agency_id is None
        else UserModel.agency_id == current_user.agency_id
    )
    result = await session.execute(
        select(UserModel)
        .where(
            UserModel.id == current_user.id,
            UserModel.role == current_user.role.value,
            agency_filter,
            UserModel.is_active.is_(True),
            UserModel.deleted_at.is_(None),
        )
        .with_for_update(of=UserModel)
        .execution_options(populate_existing=True)
    )
    actor_model = result.scalar_one_or_none()
    if actor_model is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account permissions changed. Sign in again and retry.",
        )
    return UserRepository._to_entity(actor_model)


async def _active_roster_resolution_references(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> set[uuid.UUID]:
    """Return submissions whose deletion would corrupt an active roster decision."""

    result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.client_group_id == group_id,
            PassportRosterResolutionModel.agency_id == agency_id,
            PassportRosterResolutionModel.status == "active",
        )
    )
    referenced_ids: set[uuid.UUID] = set()
    for resolution in result.scalars().all():
        referenced_ids.add(resolution.submission_id)
        for value in resolution.excluded_submission_ids or []:
            try:
                referenced_ids.add(uuid.UUID(str(value)))
            except (TypeError, ValueError, AttributeError):
                logger.warning(
                    "passport_roster_resolution_invalid_excluded_submission",
                    resolution_id=str(resolution.id),
                    value=str(value),
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "An active replacement record failed its integrity "
                        "check. Restore it before deleting passport uploads."
                    ),
                )
    return referenced_ids


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
    )
    group = mutation.group
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


@router.post(
    "/groups/{group_id}/bulk-staff-approve",
    response_model=BulkStaffApprovePassportSubmissionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Staff approve selected completed passport submissions",
)
async def bulk_staff_approve_passport_submissions(
    group_id: uuid.UUID,
    body: BulkStaffApprovePassportSubmissionsRequest,
    response: Response,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> BulkStaffApprovePassportSubmissionsResponse:
    """Atomically approve eligible rows while reporting ineligible rows."""

    allowed_roles = {
        UserRole.SUPER_ADMIN,
        UserRole.AGENCY_ADMIN,
        UserRole.AGENCY_MANAGER,
        UserRole.AGENCY_STAFF,
    }
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    actor = await _lock_active_bulk_approval_actor(session, current_user)

    group = await ClientGroupRepository(session).get_by_id(group_id)
    group_status = getattr(group, "status", None)
    group_status_value = (
        group_status.value if isinstance(group_status, GroupStatus) else group_status
    )
    if (
        not group
        or getattr(group, "deleted_at", None) is not None
        or group_status_value in {GroupStatus.ARCHIVED.value, GroupStatus.DELETED.value}
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    policy = AuthorizationPolicy(session)
    if not await policy.can_view_group(actor, group):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot approve passport submissions in this group",
        )

    selection_by_id: dict[uuid.UUID, int] = {}
    for selection in body.submissions:
        previous_revision = selection_by_id.setdefault(
            selection.submission_id,
            selection.expected_extraction_revision,
        )
        if previous_revision != selection.expected_extraction_revision:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "A selected submission was supplied with conflicting revisions. "
                    "Refresh the page and try again."
                ),
            )
    requested_ids = list(selection_by_id)
    # Lock in a stable order to avoid deadlocks between overlapping batches.
    stmt = (
        select(PassportSubmissionModel)
        .join(
            ClientGroupModel,
            ClientGroupModel.id == PassportSubmissionModel.group_id,
        )
        .where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.id.in_(requested_ids),
            ClientGroupModel.deleted_at.is_(None),
            ClientGroupModel.status.notin_([GroupStatus.ARCHIVED.value, GroupStatus.DELETED.value]),
        )
        .order_by(PassportSubmissionModel.id)
        # Lock the active group and its selected rows in one statement. Group
        # deletion and approval therefore have a deterministic order instead
        # of racing after the initial authorization snapshot.
        .with_for_update(
            of=(ClientGroupModel, PassportSubmissionModel)  # type: ignore[arg-type]
        )
    )
    stmt = AuthorizationPolicy.apply_passport_visibility_scope(stmt, actor)
    result = await session.execute(stmt)
    models = list(result.scalars().all())
    if len(models) != len(requested_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "One or more selected passport submissions were not found "
                "in this group. Refresh the page and try again."
            ),
        )

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

    try:
        if audit_rows:
            session.add_all(audit_rows)
        await session.flush()
        if approved_ids:
            await ensure_approved_passenger_qrs(
                session,
                approved_ids,
                created_by_user_id=actor.id,
            )
        await session.commit()
    except Exception:
        await session.rollback()
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "unexpected_failure",
            amount=len(requested_ids),
        )
        raise

    response.headers["Cache-Control"] = "no-store"
    if approved_ids:
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "approved",
            amount=len(approved_ids),
        )
    if already_approved_ids:
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "already_approved",
            amount=len(already_approved_ids),
        )
    if skipped:
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "skipped",
            amount=len(skipped),
        )
    return BulkStaffApprovePassportSubmissionsResponse(
        requested_count=len(requested_ids),
        approved_count=len(approved_ids),
        already_approved_count=len(already_approved_ids),
        skipped_count=len(skipped),
        approved_submission_ids=approved_ids,
        already_approved_submission_ids=already_approved_ids,
        skipped_submissions=skipped,
    )
