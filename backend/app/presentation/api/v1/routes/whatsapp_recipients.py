"""Whatsapp: recipients."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select, update
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
    ClientGroupModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
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
    _imported_field_keys_for_contacts,
    _WhatsAppExcelContactParseResult,
)
from app.presentation.api.v1.routes.whatsapp_scope import (
    _lock_active_whatsapp_actor,
    _lock_removable_broadcast_recipient,
    _prepare_private_recipient_mutation,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES,
    WHATSAPP_IN_PROGRESS_STATUSES,
    WHATSAPP_ROLES,
    WHATSAPP_UNCERTAIN_STATUSES,
    _activate_recipient_models,
    _add_rejected_contact_models,
    _agency_filter,
    _group_detail,
    _new_roster_display_orders,
    _next_roster_display_order,
    _normalize_phone,
    _normalized_recipient_inputs,
    _parse_imported_field_keys,
    _parse_manual_contacts,
    _parse_rejected_contacts,
    _rejected_contact_fingerprint,
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
        declared_keys=[*preview_field_keys, *excel_result.field_keys],
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
    protected_recipient_ids = {recipient.id}
    if target is not None and target.removed_at is not None:
        protected_recipient_ids.add(target.id)
    active_state_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel.id).where(
            WhatsAppRecipientMessageStateModel.recipient_id.in_(protected_recipient_ids),
            WhatsAppRecipientMessageStateModel.status.in_(
                WHATSAPP_IN_PROGRESS_STATUSES | WHATSAPP_UNCERTAIN_STATUSES
            ),
        )
    )
    if active_state_result.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait until the current delivery finishes, or review its unknown "
                "outcome, before changing this number"
            ),
        )
    active_log_result = await session.execute(
        select(WhatsAppMessageLogModel.id).where(
            WhatsAppMessageLogModel.recipient_id.in_(protected_recipient_ids),
            WhatsAppMessageLogModel.status.in_(WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES),
        )
    )
    if active_log_result.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait until the current delivery finishes, or review its unknown "
                "outcome, before changing this number"
            ),
        )
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
    if target is not None:
        merged_contacts = list(target.merged_contacts or [])
        incoming_contacts = list(recipient.merged_contacts or [])
        canonical_source_identity = None
        if not recipient.is_source_managed:
            canonical_source_identity = await session.scalar(
                select(WhatsAppBroadcastSourceContactModel.id).where(
                    WhatsAppBroadcastSourceContactModel.agency_id == group.agency_id,
                    WhatsAppBroadcastSourceContactModel.broadcast_group_id == group.id,
                    WhatsAppBroadcastSourceContactModel.recipient_id == recipient.id,
                    WhatsAppBroadcastSourceContactModel.name == recipient.name,
                    WhatsAppBroadcastSourceContactModel.imported_fields == (recipient.imported_fields or {}),
                ).limit(1)
            )
        if not recipient.is_source_managed and canonical_source_identity is None:
            incoming_contacts.append({
                "id": str(uuid.uuid4()),
                "source_recipient_id": str(recipient.id),
                "name": recipient.name,
                "imported_fields": dict(recipient.imported_fields or {}),
            })
        for contact in incoming_contacts:
            # A reverse merge can reactivate this very identity. A recycled
            # phone slot holding another person must retain the old snapshot.
            same_target_identity = (
                contact.get("source_recipient_id") == str(target.id)
                and contact.get("name") == target.name
                and (contact.get("imported_fields") or {}) == (target.imported_fields or {})
            )
            if not same_target_identity:
                merged_contacts.append(contact)
        target.merged_contacts = merged_contacts
        recipient.merged_contacts = []
        target.removed_at = None
        target.merged_into_recipient_id = None
        target.is_source_managed = target.is_source_managed and recipient.is_source_managed
        recipient.removed_at = now
        recipient.merged_into_recipient_id = target.id
        # Existing redirects are flat. In particular, reactivating an old alias
        # must detach it before redirecting the old canonical row back to it.
        for alias in all_recipients:
            if alias.id != target.id and alias.merged_into_recipient_id == recipient.id:
                alias.merged_into_recipient_id = target.id
    else:
        target = recipient
        recipient.phone_number = body.phone_number.strip()
        recipient.normalized_phone_number = normalized_phone
        recipient.merged_into_recipient_id = None
        await session.execute(
            update(WhatsAppRecipientMessageStateModel)
            .where(WhatsAppRecipientMessageStateModel.recipient_id == recipient.id)
            .values(
                status="failed", batch_id=None, submitted_at=None,
                provider_status_at=None, status_updated_at=now, updated_at=now,
            )
            .execution_options(synchronize_session=False)
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
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.status == "queued",
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="Recipient removed from WhatsApp broadcast before delivery",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.recipient_id == recipient.id,
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
    group.updated_at = now
    await reconcile_mobile_passenger_access_for_broadcast(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        actor_user_id=current_user.id,
    )
    return {"deleted": True}
