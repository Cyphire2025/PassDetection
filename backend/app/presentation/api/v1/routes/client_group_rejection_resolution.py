"""Rejection Resolution for upload links; HTTP declarations remain in client_groups."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    User,
)
from app.infrastructure.database.models import (
    PassportRosterResolutionModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepositoryType,
)
from app.presentation.api.v1.routes import (
    client_group_whatsapp_match_support as _whatsapp_match_support,
)
from app.presentation.api.v1.routes.client_group_operation_dependencies import (
    CurrentUnresolvedMatchContext,
    ReconcileMobilePassengerAccessForGroup,
    RequireManagedGroup,
    RequireMatchingRosterResolutionReplay,
    RequireWhatsappBroadcastAccess,
    SyncGroupBroadcastContacts,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    PassportRosterResolutionResponse,
    RejectUnidentifiedUploadRequest,
)

_roster_resolution_response = _whatsapp_match_support.roster_resolution_response


async def reject_unidentified_upload(
    link_id: uuid.UUID,
    submission_id: uuid.UUID,
    body: RejectUnidentifiedUploadRequest,
    current_user: User,
    session: AsyncSession,
    _csrf: None,
    *,
    _current_unresolved_match_context: CurrentUnresolvedMatchContext,
    _require_managed_group: RequireManagedGroup,
    _require_matching_roster_resolution_replay: RequireMatchingRosterResolutionReplay,
    _require_whatsapp_broadcast_access: RequireWhatsappBroadcastAccess,
    reconcile_mobile_passenger_access_for_group: ReconcileMobilePassengerAccessForGroup,
    sync_group_broadcast_contacts: SyncGroupBroadcastContacts,
    AuditLogRepository: type[AuditLogRepositoryType],
) -> PassportRosterResolutionResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_managed_group(session, current_user, link_id, lock=True)
    existing_result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.client_group_id == group.id,
            PassportRosterResolutionModel.request_id == body.request_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        replay = _require_matching_roster_resolution_replay(
            existing,
            client_group_id=group.id,
            submission_id=submission_id,
            resolution_type="rejected",
            broadcast_recipient_id=None,
            conflict_detail="That rejection request ID was already used.",
        )
        return _roster_resolution_response(replay)

    submission_result = await session.execute(
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.id == submission_id,
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        )
        .with_for_update()
    )
    submission = submission_result.scalar_one_or_none()
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport upload was not found in this group.",
        )
    _linked, _recipients, _submissions, match_rows = await _current_unresolved_match_context(
        session,
        group_id=group.id,
        agency_id=group.agency_id,
    )
    if not any(
        row.status == "unmatched_submission" and submission_id in row.submission_ids
        for row in match_rows
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This upload is no longer unidentified. Refresh the tracking "
                "page before rejecting it."
            ),
        )
    resolution = PassportRosterResolutionModel(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        client_group_id=group.id,
        submission_id=submission.id,
        broadcast_recipient_id=None,
        resolution_type="rejected",
        request_id=body.request_id,
        suppressed_recipient_ids=[],
        excluded_submission_ids=[],
        status="active",
        resolved_by_user_id=current_user.id,
        created_at=datetime.now(tz=UTC),
    )
    try:
        async with session.begin_nested():
            session.add(resolution)
            await session.flush()
    except IntegrityError:
        retry_result = await session.execute(
            select(PassportRosterResolutionModel).where(
                PassportRosterResolutionModel.client_group_id == group.id,
                PassportRosterResolutionModel.request_id == body.request_id,
            )
        )
        retry = retry_result.scalar_one_or_none()
        if retry is not None:
            replay = _require_matching_roster_resolution_replay(
                retry,
                client_group_id=group.id,
                submission_id=submission_id,
                resolution_type="rejected",
                broadcast_recipient_id=None,
                conflict_detail="That rejection request ID was already used.",
            )
            return _roster_resolution_response(replay)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This upload was resolved by another request. Refresh the page.",
        )
    await sync_group_broadcast_contacts(
        session,
        agency_id=group.agency_id,
        group_id=group.id,
        actor_user_id=current_user.id,
    )
    await reconcile_mobile_passenger_access_for_group(
        session,
        agency_id=group.agency_id,
        group_id=group.id,
        actor_user_id=current_user.id,
    )
    await AuditLogRepository(session).record(
        action="passport_unidentified_rejected",
        entity_type="passport_roster_resolution",
        entity_id=str(resolution.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "client_group_id": str(group.id),
            "submission_id": str(submission.id),
        },
    )
    return _roster_resolution_response(resolution)
