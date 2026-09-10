"""Authorized, concurrency-fenced corrections of client-provided group details."""

from __future__ import annotations

import uuid
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.client_details_fields import client_details_payload
from app.application.use_cases.passports.correct_client_details import correct_client_details
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    ClientGroup,
    GroupStatus,
    PassportSubmission,
    User,
)
from app.domain.exceptions.exceptions import AuthorizationError, ValidationError
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    prepare_private_delivery_identity_mutation,
)
from app.presentation.api.v1.schemas.passport_client_details_schemas import (
    PassportClientDetailsResponse,
    UpdatePassportClientDetailsRequest,
)
from app.presentation.api.v1.schemas.passport_schemas import PassportSubmissionResponse
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .response_support import _response_from_submission

router = APIRouter()


async def _editable_submission(
    submission_id: uuid.UUID,
    current_user: User,
    session: AsyncSession,
    *,
    lock: bool,
) -> tuple[PassportSubmission, ClientGroup]:
    repository = PassportSubmissionRepository(session)
    submission = await (
        repository.get_by_id_for_update(submission_id)
        if lock
        else repository.get_by_id(submission_id)
    )
    if submission is None:
        raise HTTPException(404, "Passport submission was not found")
    try:
        await AuthorizationPolicy(session).require_confirm_passport(current_user, submission)
    except AuthorizationError as exc:
        raise HTTPException(403, exc.message) from exc
    group = await ClientGroupRepository(session).get_by_id(submission.group_id)
    if group is None or group.agency_id != submission.agency_id:
        raise HTTPException(404, "Passport group was not found")
    if group.status in {GroupStatus.ARCHIVED, GroupStatus.DELETED}:
        raise HTTPException(409, "Restore this group before editing client details.")
    if submission.status.value not in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
        raise HTTPException(
            409, "Wait until the client has submitted these details before editing."
        )
    return submission, group


@router.get("/{submission_id}/client-details", response_model=PassportClientDetailsResponse)
async def get_passport_client_details(
    submission_id: uuid.UUID,
    response: Response,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportClientDetailsResponse:
    submission, group = await _editable_submission(submission_id, current_user, session, lock=False)
    response.headers["Cache-Control"] = "no-store"
    return PassportClientDetailsResponse.model_validate(client_details_payload(submission, group))


@router.patch("/{submission_id}/client-details", response_model=PassportSubmissionResponse)
async def update_passport_client_details(
    submission_id: uuid.UUID,
    body: UpdatePassportClientDetailsRequest,
    response: Response,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        before, _ = await _editable_submission(submission_id, current_user, session, lock=False)
        # Match the private-send snapshot/enqueue order: group before source rows.
        # Holding only a passenger lock before this guard would invert that order.
        locked_group = (
            await session.execute(
                select(ClientGroupModel)
                .where(
                    ClientGroupModel.id == before.group_id,
                    ClientGroupModel.agency_id == before.agency_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if locked_group is None:
            raise HTTPException(404, "Passport group was not found")
        changes = body.model_dump(mode="json", exclude_unset=True, exclude={"expected_updated_at"})
        current_group = await ClientGroupRepository(session).get_by_id(before.group_id)
        if current_group is None:
            raise HTTPException(404, "Passport group was not found")
        _, proposed_changes = correct_client_details(before, current_group, changes)
        cancelled_deliveries = 0
        if proposed_changes:
            cancelled_deliveries = await prepare_private_delivery_identity_mutation(
                session,
                agency_id=before.agency_id,
                group_id=before.group_id,
                cancel_queued=True,
                cancellation_reason="Client-provided details changed before private delivery. Refresh the preview before sending.",
            )
        submission, group = await _editable_submission(
            submission_id, current_user, session, lock=True
        )
        if submission.group_id != before.group_id or submission.agency_id != before.agency_id:
            raise HTTPException(
                409, "The submission moved while you were editing. Reload and try again."
            )
        # PostgreSQL timestamps are timezone-aware; SQLite fixtures/legacy exports
        # can be naive UTC. Compare exact instants, including microseconds.
        current = submission.updated_at
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        if current != body.expected_updated_at:
            raise HTTPException(
                409,
                "This submission changed while you were editing. Reload its details and try again.",
            )
        updated, changed_fields = correct_client_details(submission, group, changes)
        if changed_fields:
            await PassportSubmissionRepository(session).update(updated)
            await AuditLogRepository(session).record(
                action="passport_client_details_corrected",
                entity_type="passport_submission",
                entity_id=str(updated.id),
                agency_id=updated.agency_id,
                user_id=current_user.id,
                metadata={
                    "group_id": str(updated.group_id),
                    "changed_fields": list(changed_fields),
                    "cancelled_private_deliveries": cancelled_deliveries,
                },
            )
            await propagate_mobile_passenger_change(
                session,
                agency_id=updated.agency_id,
                group_id=updated.group_id,
                passenger_submission_ids=[updated.id],
                actor_user_id=current_user.id,
                change_kind="profile",
                # Even a custom detail can change ambiguous roster candidates and
                # therefore invalidate an existing private identity association.
                reconcile_identities=True,
            )
        # Persist correction, audit, and mobile invalidation atomically. No messaging,
        # verification enqueue, passport status transition, or QR issuance occurs.
        await session.commit()
    except PrivateDeliveryMutationBlocked as exc:
        await session.rollback()
        raise HTTPException(409, str(exc)) from exc
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(422, exc.message) from exc
    except Exception:
        await session.rollback()
        raise
    response.headers["Cache-Control"] = "no-store"
    return await _response_from_submission(updated, session=session)
