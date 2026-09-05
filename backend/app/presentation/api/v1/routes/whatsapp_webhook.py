"""Whatsapp: webhook."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.core.config.settings import get_settings
from app.infrastructure.database.gc_mobile_models import MobileOTPChallengeModel
from app.infrastructure.database.models import (
    DocumentWhatsAppDeliveryModel,
    PassengerQrWhatsAppDeliveryModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.whatsapp.document_delivery_runtime import (
    ACCEPTED_STATUSES as DOCUMENT_DELIVERY_ACCEPTED_STATUSES,
)
from app.infrastructure.whatsapp.document_delivery_runtime import apply_document_provider_status
from app.infrastructure.whatsapp.qr_delivery_runtime import apply_qr_provider_status
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_WEBHOOK_STATUSES,
    _apply_provider_status_to_delivery_state,
    _apply_provider_status_to_message_log,
    _extract_status_error,
    _iter_webhook_values,
    _parse_provider_status_at,
    _provider_status_state_predicates,
    logger,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppWebhookAck

router = APIRouter()


def _verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    settings = get_settings()
    app_secret = (settings.whatsapp_app_secret or "").strip()
    if not app_secret:
        return getattr(settings, "app_env", "development") == "development"
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    received_signature = signature_header.removeprefix("sha256=").strip()
    expected_signature = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_signature, expected_signature)


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_whatsapp_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    settings = get_settings()
    expected_token = (settings.whatsapp_webhook_verify_token or "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp webhook verify token is not configured",
        )
    if (
        mode == "subscribe"
        and challenge
        and hmac.compare_digest(verify_token or "", expected_token)
    ):
        return PlainTextResponse(challenge, status_code=status.HTTP_200_OK)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="WhatsApp webhook verification failed"
    )


@router.post("/webhook", response_model=WhatsAppWebhookAck)
async def receive_whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppWebhookAck:
    raw_body = await request.body()
    if not _verify_meta_signature(raw_body, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid WhatsApp webhook signature"
        )
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid WhatsApp webhook JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid WhatsApp webhook payload"
        )

    provider_statuses: list[tuple[str, str, str | None, datetime | None]] = []
    received_messages = 0
    for value in _iter_webhook_values(payload):
        for status_payload in (
            value.get("statuses", []) if isinstance(value.get("statuses"), list) else []
        ):
            if not isinstance(status_payload, dict):
                continue
            provider_id = status_payload.get("id")
            provider_status = status_payload.get("status")
            if provider_id and provider_status:
                normalized_status = str(provider_status)[:32]
                if normalized_status not in WHATSAPP_WEBHOOK_STATUSES:
                    logger.warning(
                        "Ignoring unknown WhatsApp provider status %s",
                        normalized_status,
                    )
                    continue
                provider_statuses.append(
                    (
                        str(provider_id),
                        normalized_status,
                        _extract_status_error(status_payload),
                        _parse_provider_status_at(status_payload.get("timestamp")),
                    )
                )
        messages = value.get("messages")
        if isinstance(messages, list):
            received_messages += len(messages)

    processed_statuses = 0
    released_document_changes: dict[
        tuple[uuid.UUID, uuid.UUID], tuple[set[uuid.UUID], set[str]]
    ] = {}
    provider_statuses.sort(key=lambda item: item[3] or datetime.min.replace(tzinfo=UTC))
    for (
        provider_id,
        provider_status,
        error_message,
        provider_status_at,
    ) in provider_statuses:
        processed_before = processed_statuses
        result = await session.execute(
            select(WhatsAppMessageLogModel).where(
                WhatsAppMessageLogModel.provider_message_id == provider_id
            )
        )
        message_logs = list(result.scalars().all())
        for log in message_logs:
            now = datetime.now(tz=UTC)
            _apply_provider_status_to_message_log(
                log,
                provider_status=provider_status,
                error_message=error_message,
                provider_status_at=provider_status_at,
                now=now,
            )
            if not getattr(log, "is_explicit_resend", False):
                state_result = await session.execute(
                    select(WhatsAppRecipientMessageStateModel)
                    .where(
                        *_provider_status_state_predicates(
                            log,
                            provider_status=provider_status,
                        )
                    )
                    .with_for_update()
                )
                delivery_state = state_result.scalar_one_or_none()
                if delivery_state:
                    _apply_provider_status_to_delivery_state(
                        delivery_state,
                        provider_status=provider_status,
                        provider_status_at=provider_status_at,
                        now=now,
                    )
            processed_statuses += 1
        if not message_logs:
            document_result = await session.execute(
                select(DocumentWhatsAppDeliveryModel)
                .where(DocumentWhatsAppDeliveryModel.provider_message_id == provider_id)
                .with_for_update()
            )
            document_deliveries = document_result.scalars().all()
            for delivery in document_deliveries:
                if not isinstance(delivery, DocumentWhatsAppDeliveryModel):
                    continue
                was_released = delivery.status in DOCUMENT_DELIVERY_ACCEPTED_STATUSES
                apply_document_provider_status(
                    delivery,
                    provider_status=provider_status,
                    error_message=error_message,
                    provider_status_at=provider_status_at,
                    now=datetime.now(tz=UTC),
                )
                if (
                    not was_released
                    and delivery.status in DOCUMENT_DELIVERY_ACCEPTED_STATUSES
                    and delivery.passenger_id is not None
                ):
                    passenger_ids, provider_ids = released_document_changes.setdefault(
                        (delivery.agency_id, delivery.group_id), (set(), set())
                    )
                    passenger_ids.add(delivery.passenger_id)
                    provider_ids.add(provider_id)
                processed_statuses += 1
            if not document_deliveries:
                qr_result = await session.execute(
                    select(PassengerQrWhatsAppDeliveryModel).where(
                        PassengerQrWhatsAppDeliveryModel.provider_message_id == provider_id
                    )
                )
                for qr_delivery in qr_result.scalars().all():
                    if not isinstance(qr_delivery, PassengerQrWhatsAppDeliveryModel):
                        continue
                    apply_qr_provider_status(
                        qr_delivery,
                        provider_status=provider_status,
                        error_message=error_message,
                        provider_status_at=provider_status_at,
                        now=datetime.now(tz=UTC),
                    )
                    processed_statuses += 1
        if processed_statuses == processed_before:
            otp_result = await session.execute(
                select(MobileOTPChallengeModel).where(
                    MobileOTPChallengeModel.provider_reference == provider_id
                )
            )
            challenge = otp_result.scalar_one_or_none()
            if challenge is not None:
                now = datetime.now(tz=UTC)
                if provider_status == "failed" and challenge.status == "pending":
                    challenge.status = "cancelled"
                challenge.updated_at = now
                await AuditLogRepository(session).record(
                    action="mobile.otp_delivery_status",
                    entity_type="mobile_otp_challenge",
                    agency_id=challenge.agency_id,
                    entity_id=str(challenge.id),
                    metadata={
                        "provider": challenge.provider,
                        "delivery_status": provider_status,
                        "provider_error": error_message,
                    },
                )
                if provider_status == "failed":
                    logger.warning(
                        "mobile_otp_provider_delivery_failed",
                        extra={"provider_error": error_message},
                    )
                processed_statuses += 1
    for (agency_id, group_id), (
        passenger_ids,
        provider_ids,
    ) in sorted(
        released_document_changes.items(),
        key=lambda item: (str(item[0][0]), str(item[0][1])),
    ):
        receipt_digest = hashlib.sha256("|".join(sorted(provider_ids)).encode("utf-8")).hexdigest()
        await propagate_mobile_passenger_change(
            session,
            agency_id=agency_id,
            group_id=group_id,
            passenger_submission_ids=passenger_ids,
            actor_user_id=None,
            change_kind="documents",
            reconcile_identities=False,
            propagation_key=f"document-delivery-receipt:{receipt_digest}",
        )
    if processed_statuses:
        await session.commit()

    if received_messages:
        logger.info("Received %s WhatsApp inbound message webhook event(s)", received_messages)
    return WhatsAppWebhookAck(
        processed_statuses=processed_statuses, received_messages=received_messages
    )
