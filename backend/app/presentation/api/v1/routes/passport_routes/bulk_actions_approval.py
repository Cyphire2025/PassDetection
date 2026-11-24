"""Bulk passport approval: focused scope, mutation or transaction owner."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import (
    GroupStatus,
    User,
    UserRole,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)
from app.infrastructure.qr.approved_passenger_qr_issuer import ensure_approved_passenger_qrs
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkStaffApprovePassportSubmissionsRequest,
    BulkStaffApprovePassportSubmissionsResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .bulk_actions_actor import _lock_active_bulk_approval_actor
from .bulk_actions_transitions import _apply_bulk_staff_approvals

router = APIRouter()


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
    await session.execute(
        select(ClientGroupModel.id)
        .where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == group.agency_id,
        )
        .with_for_update()
    )
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

    approved_ids, already_approved_ids, skipped, audit_rows = _apply_bulk_staff_approvals(
        models,
        selection_by_id=selection_by_id,
        actor=actor,
        group_id=group_id,
    )

    try:
        if audit_rows:
            session.add_all(audit_rows)
        await session.flush()
        if approved_ids:
            from app.application.travellers.history_schedule import schedule_submission_history
            from app.application.travellers.snapshot_access import (
                sync_approved_snapshot_participations,
            )

            await schedule_submission_history(
                session, agency_id=group.agency_id, group_id=group_id, trigger="bulk_staff_approval"
            )
            await sync_approved_snapshot_participations(
                session,
                agency_id=group.agency_id,
                group_id=group_id,
                sources=models,
                approved_ids=approved_ids,
            )
            await ensure_approved_passenger_qrs(
                session,
                approved_ids,
                created_by_user_id=actor.id,
            )
            await propagate_mobile_passenger_change(
                session,
                agency_id=group.agency_id,
                group_id=group_id,
                passenger_submission_ids=approved_ids,
                actor_user_id=actor.id,
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


bulk_staff_approve_passport_submissions.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.bulk_actions"
)
