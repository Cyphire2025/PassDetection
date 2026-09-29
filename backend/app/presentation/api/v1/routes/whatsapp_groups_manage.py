"""Whatsapp: groups manage."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastSupportContactModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.whatsapp_archive_policy import require_active_broadcast
from app.presentation.api.v1.routes.whatsapp_contact_import import (
    _parse_excel_contacts_result,
)
from app.presentation.api.v1.routes.whatsapp_contact_support import (
    _WhatsAppExcelContactParseResult,
)
from app.presentation.api.v1.routes.whatsapp_creation import (
    create_new_broadcast,
    validate_new_broadcast,
)
from app.presentation.api.v1.routes.whatsapp_scope import _lock_active_whatsapp_actor
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ROLES,
    _agency_filter,
    _clean_required_name,
    _group_detail,
    _normalize_phone,
    _parse_imported_field_keys,
    _parse_rejected_contacts,
    _parse_support_contacts,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBroadcastGroupDetailResponse,
    WhatsAppRecipientInput,
    WhatsAppSupportContactInput,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/groups",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def create_broadcast_group(
    name: str = Form(...),
    organizing_company_name: str | None = Form(None),
    contacts_json: str = Form("[]"),
    imported_field_keys_json: Annotated[str, Form()] = "[]",
    rejected_contacts_json: str = Form("[]"),
    support_contacts_json: str = Form("[]"),
    recipient_opt_in_confirmed: bool = Form(...),
    contacts_file: UploadFile | None = File(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User is not assigned to an agency"
        )
    # The authentication dependency has already performed a database read.
    # Release that transaction before parsing request JSON or workbook bytes.
    await session.rollback()
    preview_field_keys = _parse_imported_field_keys(imported_field_keys_json)
    try:
        manual_contacts = [
            WhatsAppRecipientInput(**item) for item in json.loads(contacts_json or "[]")
        ]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid manual contact list"
        ) from exc
    rejected_contacts = _parse_rejected_contacts(rejected_contacts_json)

    try:
        support_contacts = [
            WhatsAppSupportContactInput(**item)
            for item in json.loads(support_contacts_json or "[]")
        ]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid customer support contact list",
        ) from exc
    if not support_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one customer support contact",
        )

    excel_result = (
        await _parse_excel_contacts_result(contacts_file)
        if contacts_file
        else _WhatsAppExcelContactParseResult([], [], {}, [])
    )
    validate_new_broadcast(
        name=name,
        organizing_company_name=organizing_company_name,
        contacts=manual_contacts + excel_result.contacts,
        rejected_contacts=rejected_contacts,
        support_contacts=support_contacts,
        recipient_opt_in_confirmed=recipient_opt_in_confirmed,
    )
    actor = await _lock_active_whatsapp_actor(
        session,
        current_user=current_user,
        require_agency=True,
    )
    agency_id = actor.agency_id
    if agency_id is None:  # Defensive; the locked query requires an agency.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is no longer authorized for WhatsApp broadcasts.",
        )
    group = await create_new_broadcast(
        session,
        agency_id=agency_id,
        actor_id=actor.id,
        name=name,
        organizing_company_name=organizing_company_name,
        contacts=manual_contacts + excel_result.contacts,
        rejected_contacts=rejected_contacts,
        support_contacts=support_contacts,
        recipient_opt_in_confirmed=recipient_opt_in_confirmed,
        declared_field_keys=[*preview_field_keys, *excel_result.field_keys],
    )
    return await _group_detail(session, group, current_user=current_user)


@router.patch(
    "/groups/{group_id}",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_broadcast_group(
    group_id: uuid.UUID,
    name: str | None = Form(None),
    organizing_company_name: str | None = Form(None),
    support_contacts_json: str | None = Form(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )
    require_active_broadcast(group)

    if name is not None:
        group_name = name.strip()
        if not group_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group name is required",
            )
        if len(group_name) > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group name must be 100 characters or fewer",
            )
        group.name = group_name

    if organizing_company_name is not None:
        company_name = _clean_required_name(
            organizing_company_name,
            "Organising company name",
        )
        if len(company_name) > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organising company name must be 100 characters or fewer",
            )
        group.organizing_company_name = company_name

    if support_contacts_json is not None:
        support_contacts = _parse_support_contacts(support_contacts_json)
        await session.execute(
            delete(WhatsAppBroadcastSupportContactModel).where(
                WhatsAppBroadcastSupportContactModel.broadcast_group_id == group.id
            )
        )
        await session.flush()
        for sort_order, support_contact in enumerate(support_contacts):
            normalized = _normalize_phone(support_contact.phone_number)
            if not normalized:  # Defensive; _parse_support_contacts already validates.
                continue
            session.add(
                WhatsAppBroadcastSupportContactModel(
                    broadcast_group_id=group.id,
                    agency_id=group.agency_id,
                    name=_clean_required_name(
                        support_contact.name,
                        "Customer support name",
                    ),
                    phone_number=support_contact.phone_number.strip(),
                    normalized_phone_number=normalized,
                    sort_order=sort_order,
                    created_at=datetime.now(tz=UTC),
                )
            )

    group.updated_at = datetime.now(tz=UTC)
    await session.flush()
    return await _group_detail(session, group, current_user=current_user)
