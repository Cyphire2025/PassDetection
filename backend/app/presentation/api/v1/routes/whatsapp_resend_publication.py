"""Commit the audit/attempt before publication and preserve broker compensation."""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.whatsapp.publication import (
    fail_unclaimed_broadcast_rows,
    publish_whatsapp_task,
)
from app.presentation.api.v1.routes.whatsapp_resend_claims import ResendClaim
from app.presentation.api.v1.routes.whatsapp_resend_payload import resend_task_payload
from app.presentation.api.v1.routes.whatsapp_resend_preparation import PreparedResend
from app.presentation.api.v1.routes.whatsapp_shared import logger
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppSendResponse,
    WhatsAppSendResult,
)
from app.presentation.security.client_ip import trusted_client_ip


async def publish_resend_attempt(
    session: AsyncSession,
    request: Request,
    current_user: User,
    group: WhatsAppBroadcastGroupModel,
    recipient: WhatsAppBroadcastRecipientModel,
    message_type: WhatsAppMessageType,
    claim: ResendClaim,
    prepared: PreparedResend,
) -> WhatsAppSendResponse:
    is_retry = claim.is_retry
    source_log = prepared.source_log
    batch_id = prepared.batch_id
    parameters = prepared.parameters
    header_parameters = prepared.header_parameters
    await AuditLogRepository(session).record(
        action=(
            "whatsapp_recipient_message_retry_requested"
            if is_retry
            else "whatsapp_recipient_message_resend_requested"
        ),
        entity_type="whatsapp_broadcast_recipient",
        entity_id=str(recipient.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=trusted_client_ip(request),
        metadata={
            "broadcast_group_id": str(group.id),
            "message_type": message_type,
            "source_message_log_id": str(source_log.id),
            "resend_batch_id": str(batch_id),
            "source_status": source_log.status,
        },
    )
    await session.commit()
    from app.infrastructure.whatsapp.tasks import process_whatsapp_broadcast

    try:
        await publish_whatsapp_task(
            process_whatsapp_broadcast,
            payload=resend_task_payload(batch_id, message_type, parameters, header_parameters),
        )
    except Exception as exc:  # noqa: BLE001 - broker failure is surfaced and persisted.
        logger.error(
            "whatsapp_resend_queue_unavailable",
            extra={
                "batch_id": str(batch_id),
                "recipient_id": str(recipient.id),
                "error_type": type(exc).__name__,
            },
        )
        await fail_unclaimed_broadcast_rows(
            session,
            batch_id=batch_id,
            error_message=(
                "WHATSAPP_QUEUE_UNAVAILABLE: WhatsApp delivery queue is temporarily unavailable"
            ),
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp delivery queue is unavailable",
        ) from exc
    return WhatsAppSendResponse(
        batch_id=batch_id,
        queued=1,
        sent=0,
        failed=0,
        results=[
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status="queued",
            )
        ],
    )
