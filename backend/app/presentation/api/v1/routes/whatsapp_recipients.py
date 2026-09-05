"""Whatsapp: recipients."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

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
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    suppress_active_replacement_recipients,
)
from app.presentation.api.v1.routes.whatsapp_contact_import import _parse_excel_contacts
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
    rejected_contacts_json: str = Form("[]"),
    recipient_opt_in_confirmed: bool = Form(...),
    contacts_file: UploadFile | None = File(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    # Do not retain the authentication transaction (or a group row lock)
    # while reading and parsing an untrusted workbook.
    await session.rollback()
    manual_contacts = _parse_manual_contacts(contacts_json)
    rejected_contacts = _parse_rejected_contacts(rejected_contacts_json)
    excel_contacts = await _parse_excel_contacts(contacts_file) if contacts_file else []
    contacts = manual_contacts + excel_contacts
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
    return await _group_detail(session, group)


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
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = group_result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )
    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.id == recipient_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .with_for_update()
    )
    recipient = recipient_result.scalar_one_or_none()
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp recipient not found",
        )
    normalized_phone = _normalize_phone(body.phone_number)
    if not normalized_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use 8 to 15 digits with an optional country code",
        )
    duplicate_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel.id).where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.normalized_phone_number == normalized_phone,
            WhatsAppBroadcastRecipientModel.id != recipient.id,
        )
    )
    if duplicate_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That WhatsApp number already belongs to another recipient in this list",
        )
    active_state_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel.id).where(
            WhatsAppRecipientMessageStateModel.recipient_id == recipient.id,
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
    active_resend_result = await session.execute(
        select(WhatsAppMessageLogModel.id).where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status.in_(WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES),
        )
    )
    if active_resend_result.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait until the current resend finishes, or review its unknown "
                "outcome, before changing this number"
            ),
        )
    if normalized_phone == recipient.normalized_phone_number:
        return await _group_detail(session, group)

    await _prepare_private_recipient_mutation(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        recipient_id=recipient.id,
        cancellation_reason=(
            "WhatsApp recipient details changed before private document or QR delivery"
        ),
    )
    now = datetime.now(tz=UTC)
    recipient.phone_number = body.phone_number.strip()
    recipient.normalized_phone_number = normalized_phone
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(WhatsAppRecipientMessageStateModel.recipient_id == recipient.id)
        .values(
            status="failed",
            batch_id=None,
            submitted_at=None,
            provider_status_at=None,
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
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
    return await _group_detail(session, group)


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
