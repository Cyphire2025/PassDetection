"""Whatsapp: webhook."""

from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.infrastructure.database.session import get_db_session
from app.infrastructure.whatsapp.receipt_inbox import (
    parse_verified_receipts,
    persist_verified_receipts,
)
from app.infrastructure.whatsapp.receipt_runtime import reconcile_pending_receipts
from app.presentation.api.v1.routes.whatsapp_shared import logger
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
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid WhatsApp webhook JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid WhatsApp webhook payload"
        )

    events, received_messages = parse_verified_receipts(payload)
    try:
        receipt_ids = await persist_verified_receipts(session, events)
        # The verified inbox is durable even if the send has not yet committed
        # its provider ID. Do not ACK accepted statuses before this commit.
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.warning("whatsapp_receipt_persistence_failed error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp receipt storage is temporarily unavailable",
        ) from exc

    processed_statuses = 0
    if receipt_ids:
        try:
            outcomes = await reconcile_pending_receipts(session, receipt_ids=receipt_ids, limit=10)
            processed_statuses = outcomes.get("applied", 0)
        except Exception as exc:
            # Receipt storage already committed; the scheduled database sweep
            # will resume after this transient reducer/database failure.
            await session.rollback()
            logger.warning("whatsapp_receipt_deferred error_type=%s", type(exc).__name__)
    if received_messages:
        logger.info("Received %s WhatsApp inbound message webhook event(s)", received_messages)
    return WhatsAppWebhookAck(
        processed_statuses=processed_statuses, received_messages=received_messages
    )
