"""Group menu text updates with a reviewed, immutable send audience."""

from __future__ import annotations

import hmac
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.document_updates import render_document_update
from app.application.use_cases.whatsapp.template_text import normalize_template_text
from app.domain.entities.entities import User
from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.whatsapp_send_intent_models import WhatsAppSendIntentModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.whatsapp.group_update_contacts import ensure_group_update_recipient
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _lock_active_document_scope,
)
from app.presentation.api.v1.routes.document_update_preview import fingerprint
from app.presentation.api.v1.routes.group_update_preview import build_group_update_preview
from app.presentation.api.v1.schemas.document_update_schemas import SendDocumentUpdateResponse
from app.presentation.api.v1.schemas.group_update_schemas import (
    GroupUpdateAudience,
    GroupUpdatePreview,
    SendGroupUpdateRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post("/groups/{group_id}/updates/preview", response_model=GroupUpdatePreview)
async def preview_group_update(
    group_id: uuid.UUID, audience: GroupUpdateAudience,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> GroupUpdatePreview:
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    return await build_group_update_preview(session, group=group, audience=audience)


@router.post("/groups/{group_id}/updates/send", response_model=SendDocumentUpdateResponse,
             dependencies=[Depends(require_cookie_csrf)])
async def send_group_update(
    group_id: uuid.UUID, payload: SendGroupUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> SendDocumentUpdateResponse:
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    _, group = await _lock_active_document_scope(
        session, current_user=current_user, group_id=group.id, agency_id=group.agency_id,
    )
    if group.deleted_at is not None or group.status in {"archived", "deleted"}:
        raise HTTPException(409, "Restore the group before sending updates.")
    content = normalize_template_text(payload.message_content)
    if not content:
        raise HTTPException(422, "Enter the update message.")
    key = fingerprint(["group_update", str(payload.request_id)])
    request_hash = fingerprint([group_id, payload.model_dump(mode="json")])
    existing = await session.scalar(select(WhatsAppSendIntentModel).where(
        WhatsAppSendIntentModel.user_id == current_user.id,
        WhatsAppSendIntentModel.idempotency_hash == key,
    ).with_for_update())
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "This request already has different details. Refresh the preview.")
        return SendDocumentUpdateResponse.model_validate(existing.initial_response)
    preview = await build_group_update_preview(session, group=group, audience=payload.audience, lock=True)
    if not hmac.compare_digest(payload.preview_token, preview.preview_token):
        raise HTTPException(409, "The audience or delivery status changed. Refresh the preview before sending.")
    if not preview.can_send:
        raise HTTPException(409, preview.configuration_error)
    selected = set(payload.audience_keys)
    rows = [row for row in preview.recipients if row.audience_key in selected]
    if len(rows) != len(selected) or any(not row.eligible for row in rows):
        raise HTTPException(409, "Some selected contacts are no longer eligible. Refresh the preview.")
    for row in rows:
        if row.recipient_id is None and row.phone_number:
            try:
                row.recipient_id = await ensure_group_update_recipient(
                    session, agency_id=group.agency_id, broadcast_id=row.broadcast_group_id,
                    name=row.name, phone=row.phone_number,
                )
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
    phones = defaultdict(list)
    for row in rows:
        phones[row.phone_number].append(row)
    response = SendDocumentUpdateResponse(
        request_id=payload.request_id, queued_count=len(phones), passenger_count=len(rows),
        message=f"Queued {len(phones)} update messages for {len(rows)} people.",
    )
    by_broadcast = defaultdict(list)
    for phone, associated in sorted(phones.items()):
        representative = min(associated, key=lambda row: (str(row.broadcast_group_id), str(row.recipient_id)))
        by_broadcast[representative.broadcast_group_id].append((phone, representative, associated))
    intent_ids = []
    now = datetime.now(UTC)
    for index, (broadcast_id, targets) in enumerate(sorted(by_broadcast.items(), key=lambda pair: str(pair[0]))):
        batch_id = uuid.uuid4()
        for phone, representative, associated in targets:
            session.add(WhatsAppMessageLogModel(
                id=uuid.uuid4(), batch_id=batch_id, agency_id=group.agency_id,
                broadcast_group_id=broadcast_id, recipient_id=representative.recipient_id,
                normalized_phone_number=phone, message_type="document_update", status="queued",
                status_updated_at=now, template_name=preview.template_name,
                template_language=preview.template_language, rendered_message=render_document_update(content),
                header_parameter_values=[], template_parameter_values=[content],
                is_explicit_resend=False, created_at=now,
                document_update_context={
                    "audience_version": 2, "group_id": str(group_id),
                    "document_type": payload.audience.document_type,
                    "filters": payload.audience.model_dump(),
                    "audience_keys": sorted(row.audience_key for row in associated),
                    "passenger_ids": sorted(str(row.passenger_id) for row in associated if row.passenger_id),
                    "request_id": str(payload.request_id),
                },
            ))
        intent = WhatsAppSendIntentModel(
            id=uuid.uuid4(), user_id=current_user.id, agency_id=group.agency_id,
            broadcast_id=broadcast_id, idempotency_hash=key if index == 0 else fingerprint([key, broadcast_id]),
            request_hash=request_hash, initial_response=response.model_dump(mode="json"),
            worker_payload={"batch_id": str(batch_id), "message_type": "document_update"},
            batch_id=batch_id, publication_status="pending", publication_attempts=0,
            next_attempt_at=now, created_at=now, updated_at=now,
        )
        session.add(intent)
        intent_ids.append(intent.id)
    await AuditLogRepository(session).record(
        action="group_update_queued", entity_type="client_group", entity_id=str(group_id),
        agency_id=group.agency_id, user_id=current_user.id,
        metadata={"audience": payload.audience.model_dump(), "request_id": str(payload.request_id),
                  "contact_count": len(rows), "message_count": len(phones)},
    )
    await session.commit()
    from app.infrastructure.whatsapp.web_publication import run_whatsapp_send_publication
    for intent_id in intent_ids:
        await run_whatsapp_send_publication(intent_id=intent_id, limit=1)
    return response
