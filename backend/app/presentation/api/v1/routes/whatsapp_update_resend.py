"""Retry one immutable update through the existing durable update pipeline."""

import copy
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    ClientGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.whatsapp_send_intent_models import WhatsAppSendIntentModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _lock_active_document_scope,
)
from app.presentation.api.v1.routes.document_update_preview import fingerprint
from app.presentation.api.v1.routes.group_update_preview import build_group_update_preview
from app.presentation.api.v1.routes.whatsapp_archive_policy import require_active_broadcast
from app.presentation.api.v1.routes.whatsapp_history import _authorized_group
from app.presentation.api.v1.routes.whatsapp_history_resend import replay_historical_resend
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES
from app.presentation.api.v1.schemas.group_update_schemas import GroupUpdateAudience
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendResponse
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


class UpdateResendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_message_log_id: uuid.UUID
    request_id: uuid.UUID


@router.post(
    "/groups/{group_id}/recipients/{recipient_id}/resend-update",
    response_model=WhatsAppSendResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def resend_saved_update(
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    body: UpdateResendRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSendResponse:
    broadcast = await _authorized_group(session, group_id, current_user)
    require_active_broadcast(broadcast)
    recipient = await session.scalar(
        select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.id == recipient_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRecipientModel.agency_id == broadcast.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
    )
    if recipient is None:
        raise HTTPException(404, "Recipient not found in this broadcast")
    batch_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"whatsapp-update-history:{current_user.id}:{group_id}:{recipient_id}:{body.source_message_log_id}:{body.request_id}",
    )
    replay = await replay_historical_resend(
        session, batch_id=batch_id, group_id=group_id, recipient_id=recipient_id
    )
    if replay is not None:
        return replay
    source = await session.scalar(
        select(WhatsAppMessageLogModel).where(
            WhatsAppMessageLogModel.id == body.source_message_log_id,
            WhatsAppMessageLogModel.broadcast_group_id == group_id,
            WhatsAppMessageLogModel.agency_id == broadcast.agency_id,
            WhatsAppMessageLogModel.recipient_id == recipient_id,
            WhatsAppMessageLogModel.message_type == "document_update",
        )
    )
    if source is None:
        raise HTTPException(404, "The saved update was not found for this person")
    if source.status not in {"submitted", "sent", "delivered", "read", "failed"}:
        raise HTTPException(409, "Wait for a confirmed outcome before retrying this update")
    context = copy.deepcopy(source.document_update_context or {})
    try:
        client_group_id = uuid.UUID(context["group_id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, "This older update needs a fresh audience preview") from exc
    group: ClientGroupModel = await _get_authorized_group(
        client_group_id, current_user=current_user, session=session
    )
    _, group = await _lock_active_document_scope(
        session,
        current_user=current_user,
        group_id=group.id,
        agency_id=group.agency_id,
    )
    audience = GroupUpdateAudience.model_validate(
        context.get(
            "filters",
            {
                "submission_status": "all",
                "document_status": "all",
                "document_type": context.get("document_type", "visa"),
            },
        )
    )
    preview = await build_group_update_preview(session, group=group, audience=audience, lock=True)
    replay = await replay_historical_resend(
        session, batch_id=batch_id, group_id=group_id, recipient_id=recipient_id
    )
    if replay is not None:
        return replay
    original_keys = set(context.get("audience_keys", []))
    passenger_ids = set(context.get("passenger_ids", []))
    rows = [
        row
        for row in preview.recipients
        if row.broadcast_group_id == group_id
        and (
            row.audience_key in original_keys
            or str(row.passenger_id) in passenger_ids
            or row.recipient_id == recipient_id
        )
    ]
    if (
        not preview.can_send
        or not rows
        or any(not row.eligible for row in rows)
        or any(row.phone_number != recipient.normalized_phone_number for row in rows)
    ):
        raise HTTPException(
            409,
            "The audience or submitted WhatsApp number changed. Review this person in a new update.",
        )
    if (
        not source.template_name
        or not source.template_parameter_values
        or not source.rendered_message
    ):
        raise HTTPException(409, "This saved update lacks a complete template snapshot")
    context.update(
        audience_version=2,
        filters=audience.model_dump(),
        audience_keys=sorted(row.audience_key for row in rows),
        passenger_ids=sorted(str(row.passenger_id) for row in rows if row.passenger_id),
        request_id=str(body.request_id),
        source_message_log_id=str(source.id),
    )
    now = datetime.now(UTC)
    session.add(
        WhatsAppMessageLogModel(
            id=uuid.uuid4(),
            batch_id=batch_id,
            agency_id=broadcast.agency_id,
            broadcast_group_id=group_id,
            recipient_id=recipient_id,
            normalized_phone_number=recipient.normalized_phone_number,
            message_type="document_update",
            status="queued",
            status_updated_at=now,
            created_at=now,
            template_name=source.template_name,
            template_language=source.template_language,
            rendered_message=source.rendered_message,
            header_parameter_values=[],
            template_parameter_values=list(source.template_parameter_values),
            document_update_context=context,
            is_explicit_resend=False,
        )
    )
    intent_id = uuid.uuid4()
    session.add(
        WhatsAppSendIntentModel(
            id=intent_id,
            user_id=current_user.id,
            agency_id=broadcast.agency_id,
            broadcast_id=group_id,
            idempotency_hash=fingerprint(["history_update", batch_id]),
            request_hash=fingerprint(body.model_dump(mode="json")),
            initial_response={},
            batch_id=batch_id,
            worker_payload={"batch_id": str(batch_id), "message_type": "document_update"},
            publication_status="pending",
            publication_attempts=0,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    await AuditLogRepository(session).record(
        action="whatsapp_historical_update_retry",
        entity_type="whatsapp_broadcast",
        entity_id=str(group_id),
        agency_id=broadcast.agency_id,
        user_id=current_user.id,
        metadata={
            "source_message_log_id": str(source.id),
            "batch_id": str(batch_id),
            "recipient_id": str(recipient_id),
        },
    )
    await session.commit()
    from app.infrastructure.whatsapp.web_publication import run_whatsapp_send_publication

    await run_whatsapp_send_publication(intent_id=intent_id, limit=1)
    response = await replay_historical_resend(
        session, batch_id=batch_id, group_id=group_id, recipient_id=recipient_id
    )
    assert response is not None
    return response
