"""Edit manual imported contact identities without changing delivery numbers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import (
    reconcile_mobile_passenger_access_for_broadcast,
)
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_resolution_id_for_recipient,
    suppress_active_replacement_recipients,
)
from app.infrastructure.whatsapp.phone_overrides import linked_recipient_source_group_ids
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    prepare_private_delivery_identity_mutation,
)
from app.presentation.api.v1.routes.whatsapp_archive_policy import require_active_broadcast
from app.presentation.api.v1.routes.whatsapp_contact_support import (
    WHATSAPP_NON_MATCHING_IMPORTED_FIELDS,
    _safe_imported_fields,
)
from app.presentation.api.v1.routes.whatsapp_scope import (
    _lock_active_whatsapp_actor,
    _prepare_private_recipient_mutation,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ROLES,
    _agency_filter,
    _group_detail,
)
from app.presentation.api.v1.schemas.whatsapp_recipient_details_schemas import (
    WhatsAppRecipientDetailsUpdateRequest,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppBroadcastGroupDetailResponse
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
_READ_ONLY_FIELDS = WHATSAPP_NON_MATCHING_IMPORTED_FIELDS | {"phone_number", "name"}


def edited_contact_values(
    recipient: WhatsAppBroadcastRecipientModel,
    body: WhatsAppRecipientDetailsUpdateRequest,
) -> tuple[str, dict[str, str], list[dict[str, Any]] | None]:
    """Validate the original snapshot, then patch only existing editable fields."""
    contacts = [dict(contact) for contact in (recipient.merged_contacts or [])]
    contact = next(
        (item for item in contacts if item.get("id") == str(body.merged_contact_id)), None
    )
    if body.merged_contact_id is not None and contact is None:
        raise HTTPException(
            status_code=409,
            detail="This saved contact changed. Refresh the recipient list and try again.",
        )
    if contact is None and recipient.is_source_managed:
        raise HTTPException(
            status_code=409,
            detail="These details sync from a linked passport group. Edit the person's source record instead.",
        )
    old_name = contact.get("name") if contact is not None else recipient.name
    old_fields = dict(
        (contact.get("imported_fields") if contact is not None else recipient.imported_fields) or {}
    )
    if old_name != body.expected_name or old_fields != body.expected_imported_fields:
        raise HTTPException(
            status_code=409,
            detail="These details were changed by someone else. Refresh the recipient list before editing again.",
        )
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(status_code=400, detail="Enter the recipient's name.")
    allowed = old_fields.keys() - _READ_ONLY_FIELDS
    if body.imported_fields.keys() - allowed:
        raise HTTPException(
            status_code=400,
            detail="Only existing imported details can be edited. Use Edit WhatsApp number to change the delivery number.",
        )
    fields = dict(old_fields)
    for key, value in body.imported_fields.items():
        fields.pop(key, None)
        fields.update(_safe_imported_fields({key: value}))
    if "name" in fields:
        fields["name"] = name
    # Enforce the same total limits as import; retain immutable provenance bytes.
    _safe_imported_fields(fields)
    if contact is not None:
        contact.update(name=name, imported_fields=fields)
        return name, fields, contacts
    return name, fields, None


@router.patch(
    "/groups/{group_id}/recipients/{recipient_id}/details",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_broadcast_recipient_details(
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    body: WhatsAppRecipientDetailsUpdateRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    await _lock_active_whatsapp_actor(
        session, current_user=current_user, require_agency=current_user.role != UserRole.SUPER_ADMIN
    )
    initial_group = (
        await session.execute(
            select(WhatsAppBroadcastGroupModel).where(
                WhatsAppBroadcastGroupModel.id == group_id,
                *_agency_filter(current_user),
            )
        )
    ).scalar_one_or_none()
    if initial_group is None:
        raise HTTPException(status_code=404, detail="WhatsApp broadcast group not found")
    source_ids = await linked_recipient_source_group_ids(
        session, agency_id=initial_group.agency_id, broadcast_group_id=group_id
    )
    # Match passport/private-send lock order: source groups, broadcast, recipient.
    if source_ids:
        await session.execute(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id.in_(source_ids),
                ClientGroupModel.agency_id == initial_group.agency_id,
            )
            .order_by(ClientGroupModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    group = (
        await session.execute(
            select(WhatsAppBroadcastGroupModel)
            .join(AgencyModel, AgencyModel.id == WhatsAppBroadcastGroupModel.agency_id)
            .where(
                WhatsAppBroadcastGroupModel.id == group_id,
                *_agency_filter(current_user),
                AgencyModel.is_active.is_(True),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="WhatsApp broadcast group not found")
    require_active_broadcast(group)
    if source_ids != await linked_recipient_source_group_ids(
        session, agency_id=group.agency_id, broadcast_group_id=group.id
    ):
        raise HTTPException(
            status_code=409,
            detail="The linked groups changed. Refresh the recipient list and try again.",
        )
    recipient = (
        await session.execute(
            select(WhatsAppBroadcastRecipientModel)
            .where(
                WhatsAppBroadcastRecipientModel.id == recipient_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                WhatsAppBroadcastRecipientModel.merged_into_recipient_id.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if recipient is None:
        raise HTTPException(status_code=404, detail="WhatsApp recipient not found")
    if (
        recipient.suppressed_by_roster_resolution_id is not None
        or await active_replacement_resolution_id_for_recipient(session, recipient=recipient)
    ):
        raise HTTPException(
            status_code=409,
            detail="Restore the replacement in its passport group before editing this recipient.",
        )
    name, fields, contacts = edited_contact_values(recipient, body)
    unchanged = (
        contacts == recipient.merged_contacts
        if contacts is not None
        else name == recipient.name and fields == recipient.imported_fields
    )
    if unchanged:
        return await _group_detail(session, group, current_user=current_user)
    reason = "Imported contact details changed; review private document or QR delivery again."
    # Matching fields may change passenger identity even when the phone is unchanged.
    await _prepare_private_recipient_mutation(
        session, agency_id=group.agency_id, broadcast_group_id=group.id, cancellation_reason=reason
    )
    try:
        for source_id in sorted(source_ids, key=str):
            await prepare_private_delivery_identity_mutation(
                session,
                agency_id=group.agency_id,
                group_id=source_id,
                cancel_queued=True,
                cancellation_reason=reason,
            )
    except PrivateDeliveryMutationBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if contacts is None:
        recipient.name, recipient.imported_fields = name, fields
    else:
        recipient.merged_contacts = contacts
    now = datetime.now(tz=UTC)
    group.updated_at = now
    await session.flush()
    await suppress_active_replacement_recipients(
        session, agency_id=group.agency_id, broadcast_group_ids=[group.id], now=now
    )
    await session.flush()
    await reconcile_mobile_passenger_access_for_broadcast(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        actor_user_id=current_user.id,
    )
    return await _group_detail(session, group, current_user=current_user)
