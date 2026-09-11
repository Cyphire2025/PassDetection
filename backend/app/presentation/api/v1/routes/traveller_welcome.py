"""Explicit review and durable queueing of welcomes to new traveller numbers."""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.domain.entities.entities import User
from app.infrastructure.database.models import WhatsAppPhoneWelcomeAttemptModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.whatsapp.phone_welcome import (
    claim_phone_welcome,
    fail_unclaimed_traveller_welcomes,
)
from app.infrastructure.whatsapp.publication import publish_whatsapp_task
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _lock_active_document_scope,
)
from app.presentation.api.v1.routes.traveller_welcome_preview import (
    build_traveller_welcome_preview,
)
from app.presentation.api.v1.schemas.traveller_welcome_schemas import (
    SendTravellerWelcomeRequest,
    SendTravellerWelcomeResponse,
    TravellerWelcomePreview,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.get("/groups/{group_id}/whatsapp-welcome-preview", response_model=TravellerWelcomePreview)
async def preview_traveller_welcomes(
    group_id: uuid.UUID,
    source_broadcast_id: uuid.UUID | None = None,
    header_image_id: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> TravellerWelcomePreview:
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    preview, _ = await build_traveller_welcome_preview(
        session, group=group, source_broadcast_id=source_broadcast_id,
        header_image_id=header_image_id,
    )
    return preview


@router.post(
    "/groups/{group_id}/whatsapp-welcome-send", response_model=SendTravellerWelcomeResponse,
    status_code=202, dependencies=[Depends(require_cookie_csrf)],
)
async def send_traveller_welcomes(
    group_id: uuid.UUID,
    payload: SendTravellerWelcomeRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> SendTravellerWelcomeResponse:
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    _, group = await _lock_active_document_scope(
        session, current_user=current_user, group_id=group.id, agency_id=group.agency_id,
    )
    preview, content = await build_traveller_welcome_preview(
        session, group=group, source_broadcast_id=payload.source_broadcast_id, lock=True,
        header_image_id=payload.header_image_id,
    )
    if not hmac.compare_digest(preview.preview_token, payload.preview_token):
        raise HTTPException(409, "Traveller numbers or welcome content changed. Review the latest preview.")
    if not preview.template_configured or content is None or preview.source_broadcast_id is None:
        raise HTTPException(409, preview.configuration_error or "The welcome is not ready to send.")
    normalized_phones = {normalize_whatsapp_phone(phone) for phone in payload.phone_numbers}
    contacts = {row.phone_number: row for row in preview.recipients if row.phone_number}
    if None in normalized_phones or not normalized_phones.issubset(contacts):
        raise HTTPException(409, "A selected number no longer belongs to this group's approved travellers.")
    phones = {phone for phone in normalized_phones if phone is not None}
    batch_id = uuid.uuid4()
    queued = 0
    for phone in sorted(phones):
        row = contacts[phone]
        if not row.eligible:
            continue
        attempt_id = uuid.uuid4()
        claim = await claim_phone_welcome(
            session, agency_id=group.agency_id, phone=phone, attempt_id=attempt_id,
            attempt_kind="traveller",
        )
        if claim != "claimed":
            continue
        session.add(WhatsAppPhoneWelcomeAttemptModel(
            id=attempt_id, batch_id=batch_id, agency_id=group.agency_id, group_id=group.id,
            broadcast_group_id=preview.source_broadcast_id,
            passenger_ids=[str(value) for value in row.passenger_ids],
            normalized_phone_number=phone, recipient_name=", ".join(row.passenger_names)[:255],
            template_name=content.template_name, rendered_message=content.rendered_message,
            header_parameter_values=content.header_parameters,
            template_parameter_values=content.body_parameters,
            created_by_user_id=current_user.id, status="queued",
        ))
        queued += 1
    await AuditLogRepository(session).record(
        action="traveller_whatsapp_welcomes_queued", entity_type="client_group",
        agency_id=group.agency_id, user_id=current_user.id, actor_email=current_user.email,
        entity_id=str(group.id), metadata={"batch_id": str(batch_id), "queued_count": queued,
                                         "skipped_count": len(phones) - queued},
    )
    await session.commit()
    if queued:
        from app.infrastructure.whatsapp.tasks import process_traveller_welcome_broadcast

        try:
            await publish_whatsapp_task(
                process_traveller_welcome_broadcast, payload={"batch_id": str(batch_id)},
            )
        except Exception as exc:
            await fail_unclaimed_traveller_welcomes(
                session, batch_id=batch_id, error_message="The WhatsApp worker queue is temporarily unavailable.",
            )
            await session.commit()
            raise HTTPException(503, "Welcome queue is temporarily unavailable. Refresh before retrying.") from exc
    return SendTravellerWelcomeResponse(
        group_id=group.id, batch_id=batch_id if queued else None, queued_count=queued,
        skipped_count=len(phones) - queued,
        blocked_count=sum(contacts[phone].status not in {"delivered", "read"}
                          and not contacts[phone].eligible for phone in phones),
        message=(f"Queued {queued} new welcome messages. Documents unlock after delivery confirmation."
                 if queued else "No new welcomes were queued; these numbers are already welcomed or pending."),
    )
