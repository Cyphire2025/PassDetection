"""Whatsapp: recipients."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import (
    reconcile_mobile_passenger_access_for_broadcast,
)
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    ClientGroupModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_resolution_id_for_recipient,
    suppress_active_replacement_recipients,
)
from app.infrastructure.whatsapp.phone_overrides import (
    apply_recipient_traveller_phone_overrides,
    linked_recipient_source_group_ids,
    snapshot_recipient_traveller_phone_overrides,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    prepare_private_delivery_identity_mutation,
)
from app.presentation.api.v1.routes.whatsapp_archive_policy import require_active_broadcast
from app.presentation.api.v1.routes.whatsapp_contact_import import (
    _parse_excel_contacts_result,
)
from app.presentation.api.v1.routes.whatsapp_contact_support import (
    _WhatsAppExcelContactParseResult,
)
from app.presentation.api.v1.routes.whatsapp_recipient_additions import (
    add_validated_broadcast_recipients as add_validated_broadcast_recipients,
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
    _lock_removable_broadcast_recipient,
    _prepare_private_recipient_mutation,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ROLES,
    _agency_filter,
    _group_detail,
    _normalize_phone,
    _parse_imported_field_keys,
    _parse_manual_contacts,
    _parse_rejected_contacts,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBroadcastGroupDetailResponse,
    WhatsAppRecipientPhoneUpdateRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/groups/{group_id}/recipients",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def add_broadcast_recipients(
    group_id: uuid.UUID,
    contacts_json: str = Form("[]"),
    imported_field_keys_json: Annotated[str, Form()] = "[]",
    rejected_contacts_json: str = Form("[]"),
    recipient_opt_in_confirmed: bool = Form(...),
    contacts_file: UploadFile | None = File(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    # Do not retain the authentication transaction (or a group row lock)
    # while reading and parsing an untrusted workbook.
    await session.rollback()
    preview_field_keys = _parse_imported_field_keys(imported_field_keys_json)
    manual_contacts = _parse_manual_contacts(contacts_json)
    rejected_contacts = _parse_rejected_contacts(rejected_contacts_json)
    excel_result = (
        await _parse_excel_contacts_result(contacts_file)
        if contacts_file
        else _WhatsAppExcelContactParseResult([], [], {}, [])
    )
    contacts = manual_contacts + excel_result.contacts
    return await add_validated_broadcast_recipients(
        group_id=group_id, contacts=contacts, rejected_contacts=rejected_contacts,
        declared_field_keys=[*preview_field_keys, *excel_result.field_keys],
        recipient_opt_in_confirmed=recipient_opt_in_confirmed,
        current_user=current_user, session=session,
    )




@router.patch(
    "/groups/{group_id}/recipients/{recipient_id}",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_broadcast_recipient_phone(
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    body: WhatsAppRecipientPhoneUpdateRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    normalized_phone = _normalize_phone(body.phone_number)
    if not normalized_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use 8 to 15 digits with an optional country code",
        )
    await _lock_active_whatsapp_actor(
        session, current_user=current_user,
        require_agency=current_user.role != UserRole.SUPER_ADMIN,
    )
    # Passport mutations and private sends lock the source groups first. Discover
    # that scope without taking the broadcast lock, then recheck it underneath it.
    initial_group = (await session.execute(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )).scalar_one_or_none()
    if initial_group is None:
        raise HTTPException(status_code=404, detail="WhatsApp broadcast group not found")
    source_group_ids = await linked_recipient_source_group_ids(
        session, agency_id=initial_group.agency_id, broadcast_group_id=group_id,
    )
    if source_group_ids:
        await session.execute(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id.in_(source_group_ids),
                ClientGroupModel.agency_id == initial_group.agency_id,
            )
            .order_by(ClientGroupModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
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
    if source_group_ids != await linked_recipient_source_group_ids(
        session, agency_id=group.agency_id, broadcast_group_id=group.id,
    ):
        raise HTTPException(
            status_code=409,
            detail="The linked groups changed while editing this number. Please try again.",
        )
    # The broadcast lock serializes roster changes. Lock its recipient
    # set in stable order so redirects can be flattened without child lock races.
    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
        )
        .order_by(WhatsAppBroadcastRecipientModel.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    all_recipients = list(recipient_result.scalars().all())
    recipient = next((row for row in all_recipients if row.id == recipient_id
                      and row.removed_at is None and row.merged_into_recipient_id is None), None)
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp recipient not found",
        )
    target = next((row for row in all_recipients
                   if row.normalized_phone_number == normalized_phone and row.id != recipient.id), None)
    if recipient.suppressed_by_roster_resolution_id is not None or (
        target is not None and target.suppressed_by_roster_resolution_id is not None
    ) or await active_replacement_resolution_id_for_recipient(session, recipient=recipient) or (
        target is not None
        and await active_replacement_resolution_id_for_recipient(session, recipient=target)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Restore the replacement in its passport group before using this recipient.",
        )
    await require_recipient_phone_change_idle(session, recipient, target)
    if normalized_phone == recipient.normalized_phone_number:
        return await _group_detail(session, group, current_user=current_user)

    snapshots = await snapshot_recipient_traveller_phone_overrides(
        session, agency_id=group.agency_id, broadcast_group_id=group.id,
        recipient_id=recipient.id,
    )
    cancellation_reason = "WhatsApp recipient details changed before private document or QR delivery"
    # Include legacy rows with recipient_id=NULL as well as exact recipient rows.
    await _prepare_private_recipient_mutation(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        cancellation_reason=cancellation_reason,
    )
    try:
        for source_group_id in sorted({item.group_id for item in snapshots}, key=str):
            await prepare_private_delivery_identity_mutation(
                session, agency_id=group.agency_id, group_id=source_group_id,
                cancel_queued=True, cancellation_reason=cancellation_reason,
            )
    except PrivateDeliveryMutationBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    now = datetime.now(tz=UTC)
    target = await apply_recipient_phone_identity(
        session, group=group, recipient=recipient, target=target,
        all_recipients=all_recipients, phone_number=body.phone_number,
        normalized_phone=normalized_phone, now=now,
    )
    await session.flush()
    await apply_recipient_traveller_phone_overrides(
        session, agency_id=group.agency_id, broadcast_group_id=group.id,
        recipient_id=target.id, snapshots=snapshots,
    )
    group.updated_at = now
    await session.flush()
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


@router.delete(
    "/groups/{group_id}/recipients/{recipient_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_cookie_csrf)],
)
async def remove_broadcast_recipient(
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    group, recipient = await _lock_removable_broadcast_recipient(
        session,
        group_id=group_id,
        recipient_id=recipient_id,
        current_user=current_user,
    )

    await _prepare_private_recipient_mutation(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        recipient_id=recipient.id,
        cancellation_reason=(
            "WhatsApp recipient was removed before private document or QR delivery"
        ),
    )
    now = datetime.now(tz=UTC)
    recipient.removed_at = now
    await mark_removed_recipient_messages(session, recipient, now)
    group.updated_at = now
    await reconcile_mobile_passenger_access_for_broadcast(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        actor_user_id=current_user.id,
    )
    return {"deleted": True}
