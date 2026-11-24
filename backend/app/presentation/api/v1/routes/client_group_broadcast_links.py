"""Broadcast Links for upload links; HTTP declarations remain in client_groups."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    matching_field_keys_from_storage,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
)
from app.presentation.api.v1.routes.client_group_broadcast_configuration import (
    _broadcast_summaries,
    requested_link_configuration,
    summaries_with_matching_fields,
)
from app.presentation.api.v1.routes.client_group_operation_dependencies import (
    LockWhatsappBroadcastGroups,
    PreparePrivateDeliveryIdentityMutation,
    ReconcileMobilePassengerAccessForGroup,
    SuppressActiveReplacementRecipients,
    SyncGroupBroadcastContacts,
    ValidateBroadcastIds,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    WhatsAppBroadcastSummaryResponse,
)


async def _validate_broadcast_ids(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    broadcast_ids: list[uuid.UUID],
    allowed_archived_ids: list[uuid.UUID] | None,
) -> list[WhatsAppBroadcastSummaryResponse]:
    summaries = await _broadcast_summaries(
        session,
        agency_id=agency_id,
        broadcast_ids=broadcast_ids,
        allowed_archived_ids=allowed_archived_ids,
    )
    if {summary.id for summary in summaries} != set(broadcast_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("One or more WhatsApp broadcast groups are unavailable for this agency."),
        )
    return summaries


async def _replace_whatsapp_links(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    broadcast_ids: list[uuid.UUID],
    matching_fields_by_broadcast: dict[uuid.UUID, list[str]] | None,
    _validate_broadcast_ids: ValidateBroadcastIds,
    lock_whatsapp_broadcast_groups: LockWhatsappBroadcastGroups,
    prepare_private_delivery_identity_mutation: PreparePrivateDeliveryIdentityMutation,
    reconcile_mobile_passenger_access_for_group: ReconcileMobilePassengerAccessForGroup,
    suppress_active_replacement_recipients: SuppressActiveReplacementRecipients,
    sync_group_broadcast_contacts: SyncGroupBroadcastContacts,
) -> tuple[list[WhatsAppBroadcastSummaryResponse], list[uuid.UUID], bool]:
    group_result = await session.execute(
        select(ClientGroupModel)
        .where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
        )
        .with_for_update()
    )
    group_model = group_result.scalar_one()
    existing_result = await session.execute(
        select(ClientGroupWhatsAppBroadcastLinkModel).where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        )
    )
    existing_rows = list(existing_result.scalars().all())
    existing_by_broadcast = {row.broadcast_group_id: row for row in existing_rows}
    previous_configuration = {
        row.broadcast_group_id: matching_field_keys_from_storage(row.matching_field_keys)
        for row in existing_rows
    }
    previous_ids = sorted(previous_configuration, key=str)
    requested_ids = sorted(set(broadcast_ids), key=str)
    affected_broadcast_ids = sorted(
        set(previous_ids).union(requested_ids),
        key=str,
    )
    locked_broadcast_ids = await lock_whatsapp_broadcast_groups(
        session,
        agency_id=agency_id,
        broadcast_group_ids=affected_broadcast_ids,
    )
    if set(locked_broadcast_ids) != set(affected_broadcast_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "One or more WhatsApp broadcast groups changed while links "
                "were being updated. Refresh and try again."
            ),
        )
    summaries = await _validate_broadcast_ids(
        session,
        agency_id=agency_id,
        broadcast_ids=requested_ids,
        allowed_archived_ids=previous_ids,
    )
    requested_configuration = requested_link_configuration(
        summaries,
        requested_ids,
        previous_configuration,
        matching_fields_by_broadcast,
    )
    requested_sync = {
        broadcast_id: bool(
            group_model.import_only
            or (
                broadcast_id in existing_by_broadcast
                and existing_by_broadcast[broadcast_id].sync_contacts_from_group
            )
        )
        for broadcast_id in requested_ids
    }
    changed = (
        previous_ids != requested_ids
        or previous_configuration != requested_configuration
        or any(
            row.sync_contacts_from_group != requested_sync.get(row.broadcast_group_id, False)
            for row in existing_rows
        )
    )
    if changed:
        try:
            await prepare_private_delivery_identity_mutation(
                session,
                agency_id=agency_id,
                group_id=group_id,
                cancel_queued=True,
                cancellation_reason=("WhatsApp broadcast links changed before private delivery"),
            )
        except PrivateDeliveryMutationBlocked as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        removed_broadcast_ids = set(previous_ids) - set(requested_ids)
        if removed_broadcast_ids:
            active_replacement_result = await session.execute(
                select(PassportRosterResolutionModel.id)
                .join(
                    WhatsAppBroadcastRecipientModel,
                    WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id
                    == PassportRosterResolutionModel.id,
                )
                .where(
                    PassportRosterResolutionModel.client_group_id == group_id,
                    PassportRosterResolutionModel.agency_id == agency_id,
                    PassportRosterResolutionModel.status == "active",
                    PassportRosterResolutionModel.resolution_type == "replacement",
                    WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(removed_broadcast_ids),
                )
                .limit(1)
            )
            if active_replacement_result.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "A broadcast cannot be unlinked while it contains a "
                        "person marked as replaced in this passport group. "
                        "Restore the replacement first."
                    ),
                )
        for row in existing_rows:
            if row.broadcast_group_id not in requested_configuration:
                await session.delete(row)
        for broadcast_id in requested_ids:
            link_row = existing_by_broadcast.get(broadcast_id)
            if link_row is None:
                link_row = ClientGroupWhatsAppBroadcastLinkModel(
                    id=uuid.uuid4(),
                    client_group_id=group_id,
                    broadcast_group_id=broadcast_id,
                    agency_id=agency_id,
                    created_by_user_id=created_by_user_id,
                )
                session.add(link_row)
            link_row.matching_field_keys = (
                list(requested_configuration[broadcast_id] or ())
                if requested_configuration[broadcast_id] is not None
                else None
            )
            link_row.sync_contacts_from_group = requested_sync[broadcast_id]
        await session.flush()
    await sync_group_broadcast_contacts(
        session,
        agency_id=agency_id,
        group_id=group_id,
        actor_user_id=created_by_user_id,
        affected_broadcast_ids=affected_broadcast_ids,
    )
    if requested_ids:
        await suppress_active_replacement_recipients(
            session,
            agency_id=agency_id,
            broadcast_group_ids=requested_ids,
            now=datetime.now(tz=UTC),
        )
        await session.flush()
        summaries = await _validate_broadcast_ids(
            session,
            agency_id=agency_id,
            broadcast_ids=requested_ids,
            allowed_archived_ids=previous_ids,
        )
    summaries = summaries_with_matching_fields(summaries, requested_configuration)
    if changed:
        from app.application.travellers.history_schedule import schedule_group_history

        await schedule_group_history(
            session, group=group_model, trigger=f"broadcast-link:{uuid.uuid4()}"
        )
        await reconcile_mobile_passenger_access_for_group(
            session,
            agency_id=agency_id,
            group_id=group_id,
            actor_user_id=created_by_user_id,
        )
    return summaries, previous_ids, changed


async def _unique_linked_recipient_count(
    session: AsyncSession, *, group_id: uuid.UUID, agency_id: uuid.UUID
) -> int:
    result = await session.execute(
        select(WhatsAppBroadcastRecipientModel.normalized_phone_number)
        .join(
            ClientGroupWhatsAppBroadcastLinkModel,
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id
            == WhatsAppBroadcastRecipientModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            WhatsAppBroadcastRecipientModel.agency_id == agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
    )
    return len(
        {
            normalized
            for value in result.scalars().all()
            if (normalized := normalize_whatsapp_phone(value))
        }
    )
