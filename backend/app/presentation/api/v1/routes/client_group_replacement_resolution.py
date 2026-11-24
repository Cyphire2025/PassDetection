"""Replacement Resolution for upload links; HTTP declarations remain in client_groups."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    User,
)
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepositoryType,
)
from app.presentation.api.v1.routes import (
    client_group_whatsapp_match_support as _whatsapp_match_support,
)
from app.presentation.api.v1.routes.client_group_operation_dependencies import (
    CurrentUnresolvedMatchContext,
    LockWhatsappBroadcastGroups,
    ReconcileMobilePassengerAccessForGroup,
    RequireManagedGroup,
    RequireMatchingRosterResolutionReplay,
    RequireWhatsappBroadcastAccess,
    SuppressActiveReplacementRecipients,
    SyncGroupBroadcastContacts,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    PassportRosterResolutionResponse,
    ResolveUnidentifiedReplacementRequest,
)

_roster_resolution_response = _whatsapp_match_support.roster_resolution_response


async def resolve_unidentified_as_replacement(
    link_id: uuid.UUID,
    submission_id: uuid.UUID,
    body: ResolveUnidentifiedReplacementRequest,
    current_user: User,
    session: AsyncSession,
    _csrf: None,
    *,
    _current_unresolved_match_context: CurrentUnresolvedMatchContext,
    _require_managed_group: RequireManagedGroup,
    _require_matching_roster_resolution_replay: RequireMatchingRosterResolutionReplay,
    _require_whatsapp_broadcast_access: RequireWhatsappBroadcastAccess,
    lock_whatsapp_broadcast_groups: LockWhatsappBroadcastGroups,
    reconcile_mobile_passenger_access_for_group: ReconcileMobilePassengerAccessForGroup,
    suppress_active_replacement_recipients: SuppressActiveReplacementRecipients,
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
            resolution_type="replacement",
            broadcast_recipient_id=body.recipient_id,
            conflict_detail="That replacement request ID was already used.",
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

    (
        linked_broadcasts,
        _recipient_models,
        _submission_models,
        match_rows,
    ) = await _current_unresolved_match_context(
        session,
        group_id=group.id,
        agency_id=group.agency_id,
    )
    unidentified_row = next(
        (
            row
            for row in match_rows
            if row.status == "unmatched_submission" and submission_id in row.submission_ids
        ),
        None,
    )
    if unidentified_row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This upload is no longer unidentified. Refresh the tracking "
                "page before choosing a replacement."
            ),
        )

    locked_broadcast_ids = await lock_whatsapp_broadcast_groups(
        session,
        agency_id=group.agency_id,
        broadcast_group_ids=list(linked_broadcasts),
    )
    if set(locked_broadcast_ids) != set(linked_broadcasts):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The linked WhatsApp broadcasts changed. Refresh the tracking "
                "page before choosing a replacement."
            ),
        )
    live_links_result = await session.execute(
        select(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id).where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
        )
    )
    live_linked_broadcast_ids = sorted(
        set(live_links_result.scalars().all()),
        key=str,
    )
    if set(live_linked_broadcast_ids) != set(linked_broadcasts):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The linked WhatsApp broadcasts changed. Refresh the tracking "
                "page before choosing a replacement."
            ),
        )
    selected_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.id == body.recipient_id,
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(
                live_linked_broadcast_ids or [uuid.uuid4()]
            ),
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
        )
        .with_for_update()
    )
    selected_recipient = selected_result.scalar_one_or_none()
    if selected_recipient is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected recipient is no longer available for replacement.",
        )
    recipient_row = next(
        (row for row in match_rows if body.recipient_id in row.recipient_ids),
        None,
    )
    if recipient_row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected recipient could not be resolved in this group.",
        )

    suppressed_ids = list(dict.fromkeys(recipient_row.recipient_ids))
    excluded_submission_ids = list(
        dict.fromkeys(
            (
                *recipient_row.submission_ids,
                *recipient_row.candidate_submission_ids,
            )
        )
    )
    locked_recipients_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.id.in_(suppressed_ids),
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
        )
        .with_for_update()
    )
    locked_recipients = list(locked_recipients_result.scalars().all())
    if {recipient.id for recipient in locked_recipients} != set(suppressed_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One of the linked recipient records changed. Refresh and try again.",
        )

    now = datetime.now(tz=UTC)
    resolution = PassportRosterResolutionModel(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        client_group_id=group.id,
        submission_id=submission.id,
        broadcast_recipient_id=selected_recipient.id,
        replaced_recipient_normalized_phone=selected_recipient.normalized_phone_number,
        original_recipient_name=selected_recipient.name,
        original_recipient_phone=selected_recipient.phone_number,
        original_recipient_imported_fields=dict(selected_recipient.imported_fields or {}),
        resolution_type="replacement",
        request_id=body.request_id,
        suppressed_recipient_ids=[str(recipient_id) for recipient_id in suppressed_ids],
        excluded_submission_ids=[
            str(original_submission_id) for original_submission_id in excluded_submission_ids
        ],
        status="active",
        resolved_by_user_id=current_user.id,
        created_at=now,
    )
    try:
        async with session.begin_nested():
            session.add(resolution)
            for recipient in locked_recipients:
                recipient.removed_at = now
                recipient.suppressed_by_roster_resolution_id = resolution.id
            await session.execute(
                update(WhatsAppMessageLogModel)
                .where(
                    WhatsAppMessageLogModel.recipient_id.in_(suppressed_ids),
                    WhatsAppMessageLogModel.status == "queued",
                )
                .values(
                    status="failed",
                    status_updated_at=now,
                    error_message=("Recipient replaced in linked passport group before delivery"),
                )
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                update(WhatsAppRecipientMessageStateModel)
                .where(
                    WhatsAppRecipientMessageStateModel.recipient_id.in_(suppressed_ids),
                    WhatsAppRecipientMessageStateModel.status == "queued",
                )
                .values(
                    status="failed",
                    batch_id=None,
                    status_updated_at=now,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                update(WhatsAppBroadcastGroupModel)
                .where(
                    WhatsAppBroadcastGroupModel.id.in_(
                        list({recipient.broadcast_group_id for recipient in locked_recipients})
                    )
                )
                .values(updated_at=now)
            )
            await session.flush()
            await suppress_active_replacement_recipients(
                session,
                agency_id=group.agency_id,
                broadcast_group_ids=list(linked_broadcasts),
                now=now,
            )
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
                resolution_type="replacement",
                broadcast_recipient_id=body.recipient_id,
                conflict_detail="That replacement request ID was already used.",
            )
            return _roster_resolution_response(replay)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This upload or recipient was resolved by another request. "
                "Refresh the tracking page."
            ),
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
        action="passport_unidentified_marked_replacement",
        entity_type="passport_roster_resolution",
        entity_id=str(resolution.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "client_group_id": str(group.id),
            "replacement_submission_id": str(submission.id),
            "selected_recipient_id": str(selected_recipient.id),
            "suppressed_recipient_ids": [str(recipient_id) for recipient_id in suppressed_ids],
            "excluded_submission_ids": list(resolution.excluded_submission_ids),
        },
    )
    return _roster_resolution_response(resolution)


def _require_matching_roster_resolution_replay(
    resolution: PassportRosterResolutionModel,
    *,
    client_group_id: uuid.UUID,
    submission_id: uuid.UUID,
    resolution_type: Literal["replacement", "rejected"],
    broadcast_recipient_id: uuid.UUID | None,
    conflict_detail: str,
) -> PassportRosterResolutionModel:
    if (
        resolution.client_group_id != client_group_id
        or resolution.submission_id != submission_id
        or resolution.resolution_type != resolution_type
        or resolution.broadcast_recipient_id != broadcast_recipient_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=conflict_detail,
        )
    return resolution
