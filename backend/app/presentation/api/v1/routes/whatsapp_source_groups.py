"""Preview and create broadcasts from active, accessible passport groups."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import (
    reconcile_mobile_passenger_access_for_group,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.whatsapp.recipient_capacity import (
    WhatsAppRecipientCapacityExceeded,
    require_whatsapp_recipient_capacity,
)
from app.application.use_cases.whatsapp.source_group_contacts import build_source_contacts
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, GroupStatus, User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    suppress_active_replacement_recipients,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    prepare_private_delivery_identity_mutation,
)
from app.presentation.api.v1.routes.whatsapp_contact_support import (
    _clean_required_name,
    _normalize_phone,
    _parse_support_contacts,
)
from app.presentation.api.v1.routes.whatsapp_scope import _lock_active_whatsapp_actor
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES, _group_detail
from app.presentation.api.v1.schemas.whatsapp_source_group_schemas import (
    WhatsAppSourceGroupCreateRequest,
    WhatsAppSourceGroupCreateResponse,
    WhatsAppSourceGroupOption,
    WhatsAppSourceGroupPreview,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


def _source_group_statement(current_user: User):  # type: ignore[no-untyped-def]
    # Even a super admin must create in the effective agency, matching normal
    # broadcast creation. Group visibility alone deliberately allows all agencies.
    statement = select(ClientGroupModel).where(
        ClientGroupModel.agency_id == current_user.agency_id,
        ClientGroupModel.status == GroupStatus.ACTIVE.value,
        ClientGroupModel.deleted_at.is_(None),
    )
    return AuthorizationPolicy.apply_group_visibility_scope(statement, current_user)


async def _source_group(
    group_id: uuid.UUID, current_user: User, session: AsyncSession, *, lock: bool = False,
) -> ClientGroupModel:
    statement = _source_group_statement(current_user).where(ClientGroupModel.id == group_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    group = (await session.execute(statement)).scalar_one_or_none()
    if group is None:
        raise HTTPException(404, "Active passport group was not found or is not accessible.")
    try:
        await AuthorizationPolicy(session).require_manage_group(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(403, exc.message) from exc
    return cast(ClientGroupModel, group)


async def _source_preview(
    group: ClientGroupModel, session: AsyncSession, *, lock: bool = False,
) -> WhatsAppSourceGroupPreview:
    statement = select(PassportSubmissionModel).where(
        PassportSubmissionModel.group_id == group.id,
        PassportSubmissionModel.agency_id == group.agency_id,
        PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        operational_roster_member(),
    ).order_by(PassportSubmissionModel.created_at, PassportSubmissionModel.id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    submissions = (await session.execute(statement)).scalars().all()
    return WhatsAppSourceGroupPreview.model_validate(
        build_source_contacts(group.id, group.name, submissions)
    )


@router.get("/source-groups", response_model=list[WhatsAppSourceGroupOption])
async def list_source_groups(
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[WhatsAppSourceGroupOption]:
    statement = _source_group_statement(current_user).add_columns(
        func.count(PassportSubmissionModel.id)
    ).outerjoin(PassportSubmissionModel, and_(
        PassportSubmissionModel.group_id == ClientGroupModel.id,
        PassportSubmissionModel.agency_id == ClientGroupModel.agency_id,
        PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        operational_roster_member(),
    )).group_by(ClientGroupModel.id).order_by(ClientGroupModel.created_at.desc())
    rows = (await session.execute(statement)).all()
    return [
        WhatsAppSourceGroupOption(id=group.id, name=group.name, submission_count=count)
        for group, count in rows
    ]


@router.get("/source-groups/{group_id}/preview", response_model=WhatsAppSourceGroupPreview)
async def preview_source_group(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSourceGroupPreview:
    group = await _source_group(group_id, current_user, session)
    return await _source_preview(group, session)


@router.post(
    "/groups/from-client-group", response_model=WhatsAppSourceGroupCreateResponse,
    status_code=201, dependencies=[Depends(require_cookie_csrf)],
)
async def create_broadcast_from_source_group(
    body: WhatsAppSourceGroupCreateRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSourceGroupCreateResponse:
    if not body.recipient_opt_in_confirmed:
        raise HTTPException(400, "Confirm recipient WhatsApp opt-in before saving this list")
    support_contacts = _parse_support_contacts(json.dumps([
        contact.model_dump() for contact in body.support_contacts
    ]))
    await session.rollback()
    actor = await _lock_active_whatsapp_actor(session, current_user=current_user, require_agency=True)
    effective_actor = cast(User, actor)
    source = await _source_group(body.source_group_id, effective_actor, session, lock=True)
    preview = await _source_preview(source, session, lock=True)
    if preview.preview_revision != body.preview_revision:
        raise HTTPException(409, "The source group changed. Refresh its preview and confirm the recipients again.")
    if not preview.recipient_count:
        raise HTTPException(400, "This group has no usable named WhatsApp recipients.")
    try:
        require_whatsapp_recipient_capacity(active_count=0, activating_count=preview.recipient_count)
    except WhatsAppRecipientCapacityExceeded as exc:
        raise HTTPException(400, "A WhatsApp broadcast can contain at most 1500 recipients.") from exc
    try:
        await prepare_private_delivery_identity_mutation(
            session, agency_id=source.agency_id, group_id=source.id,
            cancel_queued=True,
            cancellation_reason="A source-group broadcast link changed before private delivery",
        )
    except PrivateDeliveryMutationBlocked as exc:
        raise HTTPException(409, str(exc)) from exc
    now = datetime.now(tz=UTC)
    group = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(), agency_id=source.agency_id, name=body.name,
        organizing_company_name=body.organizing_company_name or "",
        recipient_opt_in_confirmed_at=now,
        imported_field_keys=["name", "given_names", "surname", "phone_number"],
        created_by_user_id=actor.id, created_at=now, updated_at=now,
    )
    session.add(group)
    for order, contact in enumerate(preview.recipients, 1):
        session.add(WhatsAppBroadcastRecipientModel(
            broadcast_group_id=group.id, agency_id=source.agency_id,
            name=contact.name, phone_number=contact.phone_number,
            normalized_phone_number=contact.phone_number, imported_fields=contact.imported_fields,
            display_order=order, created_at=now,
        ))
    for order, support_contact in enumerate(support_contacts):
        session.add(WhatsAppBroadcastSupportContactModel(
            broadcast_group_id=group.id, agency_id=source.agency_id,
            name=_clean_required_name(support_contact.name, "Customer support name"), phone_number=support_contact.phone_number,
            normalized_phone_number=_normalize_phone(support_contact.phone_number),
            sort_order=order, created_at=now,
        ))
    # Append metadata instead of replacing the group's existing broadcast links.
    session.add(ClientGroupWhatsAppBroadcastLinkModel(
        client_group_id=source.id, broadcast_group_id=group.id, agency_id=source.agency_id,
        created_by_user_id=actor.id, matching_field_keys=["phone_number"], created_at=now,
    ))
    await session.flush()
    await suppress_active_replacement_recipients(
        session, agency_id=source.agency_id, broadcast_group_ids=[group.id], now=now,
    )
    await session.flush()
    await reconcile_mobile_passenger_access_for_group(
        session, agency_id=source.agency_id, group_id=source.id, actor_user_id=actor.id,
    )
    return WhatsAppSourceGroupCreateResponse(
        group=await _group_detail(session, group, current_user=effective_actor), source=preview,
    )
