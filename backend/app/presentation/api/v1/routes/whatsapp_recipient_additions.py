"""Canonical flush-only contact addition shared by the dashboard and MCP."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import (
    reconcile_mobile_passenger_access_for_broadcast,
)
from app.application.use_cases.whatsapp.recipient_capacity import (
    MAX_WHATSAPP_RECIPIENTS,
    WhatsAppRecipientCapacityExceeded,
    require_whatsapp_recipient_capacity,
)
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
)
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    suppress_active_replacement_recipients,
)
from app.presentation.api.v1.routes.whatsapp_archive_policy import require_active_broadcast
from app.presentation.api.v1.routes.whatsapp_contact_support import (
    _imported_field_keys_for_contacts,
)
from app.presentation.api.v1.routes.whatsapp_recipient_phone_identity import (
    apply_recipient_phone_identity as apply_recipient_phone_identity,
)
from app.presentation.api.v1.routes.whatsapp_recipient_phone_identity import (
    mark_removed_recipient_messages as mark_removed_recipient_messages,
)
from app.presentation.api.v1.routes.whatsapp_recipient_phone_identity import (
    require_recipient_phone_change_idle as require_recipient_phone_change_idle,
)
from app.presentation.api.v1.routes.whatsapp_scope import (
    _lock_active_whatsapp_actor,
    _prepare_private_recipient_mutation,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _activate_recipient_models,
    _add_rejected_contact_models,
    _group_detail,
    _new_roster_display_orders,
    _next_roster_display_order,
    _normalized_recipient_inputs,
    _rejected_contact_fingerprint,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBroadcastGroupDetailResponse,
    WhatsAppRecipientInput,
    WhatsAppRejectedContactInput,
)


async def add_validated_broadcast_recipients(
    *, group_id: uuid.UUID, contacts: list[WhatsAppRecipientInput],
    rejected_contacts: list[WhatsAppRejectedContactInput], declared_field_keys: list[str],
    recipient_opt_in_confirmed: bool, current_user: User, session: AsyncSession,
) -> WhatsAppBroadcastGroupDetailResponse:
    """Shared flush-only persistence after untrusted workbook parsing has finished."""
    normalized_contacts = _normalized_recipient_inputs(contacts) if contacts else {}
    if not normalized_contacts and not rejected_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one valid or rejected WhatsApp contact",
        )
    if normalized_contacts and not recipient_opt_in_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm recipient WhatsApp opt-in before adding contacts",
        )

    actor = await _lock_active_whatsapp_actor(
        session,
        current_user=current_user,
        require_agency=current_user.role != UserRole.SUPER_ADMIN,
    )
    group_predicates = [WhatsAppBroadcastGroupModel.id == group_id]
    if actor.role != UserRole.SUPER_ADMIN.value:
        group_predicates.append(WhatsAppBroadcastGroupModel.agency_id == actor.agency_id)
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .join(AgencyModel, AgencyModel.id == WhatsAppBroadcastGroupModel.agency_id)
        .where(*group_predicates, AgencyModel.is_active.is_(True))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    group = group_result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )
    require_active_broadcast(group)

    existing_by_phone: dict[str, WhatsAppBroadcastRecipientModel] = {}
    if normalized_contacts:
        existing_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id
            )
        )
        existing_by_phone = {
            recipient.normalized_phone_number: recipient
            for recipient in existing_result.scalars().all()
        }
        active_count = sum(
            1 for recipient in existing_by_phone.values() if recipient.removed_at is None
        )
        activating_count = sum(
            1
            for normalized in normalized_contacts
            if normalized not in existing_by_phone
            or existing_by_phone[normalized].removed_at is not None
        )
        try:
            require_whatsapp_recipient_capacity(
                active_count=active_count,
                activating_count=activating_count,
                broadcast_group_id=group.id,
            )
        except WhatsAppRecipientCapacityExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"A WhatsApp list can contain at most {MAX_WHATSAPP_RECIPIENTS} recipients"
                ),
            ) from exc

    if normalized_contacts:
        await _prepare_private_recipient_mutation(
            session,
            agency_id=group.agency_id,
            broadcast_group_id=group.id,
            cancellation_reason=(
                "WhatsApp recipients changed before private document or QR delivery"
            ),
        )
    existing_rejected_by_fingerprint: dict[
        str,
        WhatsAppBroadcastRejectedContactModel,
    ] = {}
    if rejected_contacts:
        existing_rejected_result = await session.execute(
            select(WhatsAppBroadcastRejectedContactModel).where(
                WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group.id,
            )
        )
        existing_rejected_contacts = list(existing_rejected_result.scalars().all())
        existing_rejected_by_fingerprint = {
            contact.fingerprint: contact for contact in existing_rejected_contacts
        }

    new_roster_count = sum(
        1 for normalized in normalized_contacts if normalized not in existing_by_phone
    ) + sum(
        1
        for contact in rejected_contacts
        if _rejected_contact_fingerprint(contact) not in existing_rejected_by_fingerprint
    )
    start_order = await _next_roster_display_order(session, group.id) if new_roster_count else 1
    recipient_display_orders, rejected_display_orders = _new_roster_display_orders(
        normalized_contacts=normalized_contacts,
        rejected_contacts=rejected_contacts,
        existing_by_phone=existing_by_phone,
        existing_by_fingerprint=existing_rejected_by_fingerprint,
        start_order=start_order,
    )

    now = datetime.now(tz=UTC)
    group.imported_field_keys = _imported_field_keys_for_contacts(
        getattr(group, "imported_field_keys", []),
        declared_keys=declared_field_keys,
        contacts=[*contacts, *rejected_contacts],
    )
    _activate_recipient_models(
        session=session,
        group=group,
        existing_by_phone=existing_by_phone,
        normalized_contacts=normalized_contacts,
        now=now,
        display_orders_by_phone=recipient_display_orders,
    )
    if rejected_contacts:
        _add_rejected_contact_models(
            session=session,
            group=group,
            contacts=rejected_contacts,
            existing_by_fingerprint=existing_rejected_by_fingerprint,
            now=now,
            display_orders_by_fingerprint=rejected_display_orders,
        )

    if normalized_contacts:
        group.recipient_opt_in_confirmed_at = group.recipient_opt_in_confirmed_at or now
    group.updated_at = now
    await session.flush()
    if normalized_contacts:
        await suppress_active_replacement_recipients(
            session,
            agency_id=group.agency_id,
            broadcast_group_ids=[group.id],
            now=now,
        )
        await session.flush()
        await reconcile_mobile_passenger_access_for_broadcast(
            session,
            agency_id=group.agency_id,
            broadcast_group_id=group.id,
            actor_user_id=current_user.id,
        )
    return await _group_detail(session, group, current_user=current_user)
