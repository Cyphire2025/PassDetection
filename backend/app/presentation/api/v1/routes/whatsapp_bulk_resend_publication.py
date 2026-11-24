"""Commit private-safe request receipts before publishing the frozen batch."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.models import WhatsAppBroadcastGroupModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.whatsapp.publication import (
    fail_unclaimed_broadcast_rows,
    publish_whatsapp_task,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_claims import BulkResendClaims
from app.presentation.api.v1.routes.whatsapp_bulk_resend_selection import AUDIT_ACTION
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    build_response,
    refresh_batch_response,
)
from app.presentation.api.v1.routes.whatsapp_resend_payload import resend_task_payload
from app.presentation.api.v1.routes.whatsapp_shared import logger
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendRequest,
    WhatsAppBulkResendResponse,
)
from app.presentation.security.client_ip import trusted_client_ip


async def publish_bulk_resend(
    session: AsyncSession,
    request: Request,
    current_user: User,
    group: WhatsAppBroadcastGroupModel,
    body: WhatsAppBulkResendRequest,
    request_scope: uuid.UUID,
    fingerprint: str,
    claims: BulkResendClaims,
) -> WhatsAppBulkResendResponse:
    logs = claims.logs
    results = claims.results
    batch_id = claims.batch_id
    if logs:
        settings = get_settings()
        if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
            await session.rollback()
            raise HTTPException(
                status_code=503, detail="WhatsApp Cloud API credentials are incomplete"
            )
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A resend is already active for part of this selection; refresh the list",
        ) from exc
    response = build_response(batch_id=batch_id if logs else None, results=results)
    receipt_response = response.model_dump(mode="json")
    for item in receipt_response["results"]:
        item["phone_number"] = ""
    await AuditLogRepository(session).record(
        action=AUDIT_ACTION,
        entity_type="whatsapp_bulk_resend_request",
        entity_id=str(request_scope),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=trusted_client_ip(request),
        metadata={
            "broadcast_group_id": str(group.id),
            "message_type": body.message_type,
            "selection_fingerprint": fingerprint,
            "response": receipt_response,
        },
    )
    await session.commit()
    if not logs:
        return response
    from app.infrastructure.whatsapp.tasks import process_whatsapp_broadcast

    first = logs[0]
    parameters = first.template_parameter_values or []
    header = first.header_parameter_values or []
    try:
        await publish_whatsapp_task(
            process_whatsapp_broadcast,
            payload=resend_task_payload(batch_id, body.message_type, parameters, header),
        )
    except Exception as exc:  # noqa: BLE001 - Persist conservative publication compensation.
        logger.error(
            "whatsapp_selected_resend_queue_unavailable",
            extra={"batch_id": str(batch_id), "error_type": type(exc).__name__},
        )
        await fail_unclaimed_broadcast_rows(
            session,
            batch_id=batch_id,
            error_message="WHATSAPP_QUEUE_UNAVAILABLE: WhatsApp delivery queue is temporarily unavailable",
        )
        await session.commit()
        return await refresh_batch_response(session, response, replayed=False)
    return response
