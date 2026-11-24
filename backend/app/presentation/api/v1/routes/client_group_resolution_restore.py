"""Resolution Restore for upload links; HTTP declarations remain in client_groups."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.recipient_capacity import (
    MAX_WHATSAPP_RECIPIENTS,
    WhatsAppRecipientCapacityExceeded,
)
from app.domain.entities.entities import (
    User,
)
from app.infrastructure.database.models import (
    PassportRosterResolutionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepositoryType,
)
from app.presentation.api.v1.routes import (
    client_group_whatsapp_match_support as _whatsapp_match_support,
)
from app.presentation.api.v1.routes.client_group_operation_dependencies import (
    LockWhatsappBroadcastGroups,
    ReconcileMobilePassengerAccessForGroup,
    RequireLockedBroadcastRecipientCapacity,
    RequireManagedGroup,
    RequireWhatsappBroadcastAccess,
    SuppressActiveReplacementRecipients,
    SyncGroupBroadcastContacts,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    PassportRosterResolutionResponse,
)

_roster_resolution_response = _whatsapp_match_support.roster_resolution_response


async def restore_roster_resolution(
    link_id: uuid.UUID,
    resolution_id: uuid.UUID,
    current_user: User,
    session: AsyncSession,
    _csrf: None,
    *,
    _require_managed_group: RequireManagedGroup,
    _require_whatsapp_broadcast_access: RequireWhatsappBroadcastAccess,
    lock_whatsapp_broadcast_groups: LockWhatsappBroadcastGroups,
    reconcile_mobile_passenger_access_for_group: ReconcileMobilePassengerAccessForGroup,
    require_locked_broadcast_recipient_capacity: RequireLockedBroadcastRecipientCapacity,
    suppress_active_replacement_recipients: SuppressActiveReplacementRecipients,
    sync_group_broadcast_contacts: SyncGroupBroadcastContacts,
    AuditLogRepository: type[AuditLogRepositoryType],
) -> PassportRosterResolutionResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_managed_group(session, current_user, link_id, lock=True)
    preliminary_result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.id == resolution_id,
            PassportRosterResolutionModel.client_group_id == group.id,
            PassportRosterResolutionModel.agency_id == group.agency_id,
        )
    )
    preliminary_resolution = preliminary_result.scalar_one_or_none()
    if preliminary_resolution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Roster resolution was not found.",
        )
    if preliminary_resolution.status == "restored":
        return _roster_resolution_response(preliminary_resolution)

    broadcast_ids: list[uuid.UUID] = []
    locked_broadcast_ids: list[uuid.UUID] = []
    if preliminary_resolution.resolution_type == "replacement":
        broadcast_ids_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel.broadcast_group_id).where(
                WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id
                == preliminary_resolution.id,
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            )
        )
        broadcast_ids = list(dict.fromkeys(broadcast_ids_result.scalars().all()))
        locked_broadcast_ids = await lock_whatsapp_broadcast_groups(
            session,
            agency_id=group.agency_id,
            broadcast_group_ids=broadcast_ids,
        )

    # Every path that can suppress or reactivate recipients takes broadcast
    # locks before the resolution lock. Keep the same global order here.
    result = await session.execute(
        select(PassportRosterResolutionModel)
        .where(
            PassportRosterResolutionModel.id == resolution_id,
            PassportRosterResolutionModel.client_group_id == group.id,
            PassportRosterResolutionModel.agency_id == group.agency_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    resolution = result.scalar_one_or_none()
    if resolution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Roster resolution was not found.",
        )
    if resolution.status == "restored":
        return _roster_resolution_response(resolution)

    now = datetime.now(tz=UTC)
    restored_recipient_ids: list[uuid.UUID] = []
    if resolution.resolution_type == "replacement":
        recipients_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel)
            .where(
                WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id == resolution.id,
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            )
            .with_for_update()
        )
        recipients = list(recipients_result.scalars().all())
        live_broadcast_ids = {recipient.broadcast_group_id for recipient in recipients}
        if not live_broadcast_ids.issubset(set(locked_broadcast_ids)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The linked WhatsApp recipients changed while the replacement "
                    "was being restored. Refresh and try again."
                ),
            )
        activating_by_broadcast: dict[uuid.UUID, int] = {}
        for recipient in recipients:
            if recipient.removed_at is not None:
                activating_by_broadcast[recipient.broadcast_group_id] = (
                    activating_by_broadcast.get(recipient.broadcast_group_id, 0) + 1
                )
        try:
            await require_locked_broadcast_recipient_capacity(
                session,
                agency_id=group.agency_id,
                locked_broadcast_ids=locked_broadcast_ids,
                activating_by_broadcast=activating_by_broadcast,
            )
        except WhatsAppRecipientCapacityExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Restoring this replacement would exceed the maximum of "
                    f"{MAX_WHATSAPP_RECIPIENTS} recipients in a WhatsApp list."
                ),
            ) from exc
        for recipient in recipients:
            recipient.removed_at = None
            recipient.suppressed_by_roster_resolution_id = None
            restored_recipient_ids.append(recipient.id)
        if recipients:
            await session.execute(
                update(WhatsAppBroadcastGroupModel)
                .where(
                    WhatsAppBroadcastGroupModel.id.in_(
                        list({recipient.broadcast_group_id for recipient in recipients})
                    )
                )
                .values(updated_at=now)
            )
    resolution.status = "restored"
    resolution.restored_by_user_id = current_user.id
    resolution.restored_at = now
    await session.flush()
    if resolution.resolution_type == "replacement":
        await suppress_active_replacement_recipients(
            session,
            agency_id=group.agency_id,
            broadcast_group_ids=broadcast_ids,
            now=now,
        )
        await session.flush()
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
        action="passport_roster_resolution_restored",
        entity_type="passport_roster_resolution",
        entity_id=str(resolution.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "client_group_id": str(group.id),
            "submission_id": str(resolution.submission_id),
            "resolution_type": resolution.resolution_type,
            "restored_recipient_ids": [
                str(recipient_id) for recipient_id in restored_recipient_ids
            ],
        },
    )
    return _roster_resolution_response(resolution)
