"""Pure projection of prepared sends, claim accounting and the frozen worker payload."""

from __future__ import annotations

import uuid
from typing import Literal, cast

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.presentation.api.v1.routes.whatsapp_send_claims import ClaimedBroadcastSend
from app.presentation.api.v1.routes.whatsapp_send_preparation import PreparedBroadcastSend
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppSendRequest,
    WhatsAppSendResponse,
    WhatsAppSendResult,
)


def build_broadcast_send_response(
    prepared: PreparedBroadcastSend,
    claims: ClaimedBroadcastSend,
    *,
    batch_id: uuid.UUID | None,
    queued: int,
    results: list[WhatsAppSendResult],
) -> WhatsAppSendResponse:
    return WhatsAppSendResponse(
        batch_id=batch_id,
        audience=cast(Literal["all", "not_submitted"], prepared.audience_resolution.audience),
        audience_client_group_id=prepared.audience_resolution.client_group_id,
        recipient_count=len(prepared.source_recipients),
        audience_recipient_count=len(prepared.recipients),
        excluded_submitted_count=prepared.audience_resolution.excluded_submitted_count,
        excluded_needs_review_count=prepared.audience_resolution.excluded_needs_review_count,
        queued=queued,
        sent=0,
        failed=0,
        skipped_already_sent=claims.skipped_already_sent,
        skipped_in_progress=claims.skipped_in_progress,
        skipped_delivery_unknown=claims.skipped_delivery_unknown,
        results=results,
    )


def broadcast_send_worker_payload(
    *,
    batch_id: uuid.UUID,
    message_type: WhatsAppMessageType,
    message_content: str,
    passport_intro: str | None,
    passport_link: str | None,
    resolved_body: WhatsAppSendRequest,
) -> dict[str, object]:
    return {
        "batch_id": str(batch_id),
        "message_type": message_type,
        "message_content": message_content,
        "passport_intro": passport_intro,
        "passport_link": passport_link,
        "group_invite_link": resolved_body.group_invite_link,
        "header_image_id": resolved_body.header_image_id,
    }
