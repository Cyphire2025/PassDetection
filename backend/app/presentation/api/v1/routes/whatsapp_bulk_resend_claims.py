"""Claim overlapping phones canonically while retaining requested result order."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import GroupInviteImageRequired
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.phone_welcome import claim_phone_welcome
from app.presentation.api.v1.routes.whatsapp_bulk_resend_inputs import BulkResendInputs
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    SKIP_MESSAGES,
    frozen_resend_log,
    recipient_skip_reason,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendRequest,
    WhatsAppSendResult,
)


@dataclass(frozen=True)
class BulkResendClaims:
    batch_id: uuid.UUID
    logs: list[WhatsAppMessageLogModel]
    results: list[WhatsAppSendResult]


async def claim_bulk_welcome(
    session: AsyncSession,
    group: WhatsAppBroadcastGroupModel,
    recipient: WhatsAppBroadcastRecipientModel,
    log: WhatsAppMessageLogModel,
    batch_id: uuid.UUID,
) -> str | None:
    reason: str | None = None
    phone_status = await claim_phone_welcome(
        session,
        agency_id=group.agency_id,
        phone=recipient.normalized_phone_number,
        attempt_id=log.id,
        attempt_kind="broadcast",
        broadcast_group_id=group.id,
        batch_id=batch_id,
        explicit_resend=log.is_explicit_resend,
    )
    if phone_status != "claimed":
        reason = (
            "skipped_in_progress"
            if phone_status in {"queued", "processing"}
            else "skipped_delivery_unknown"
            if phone_status == "delivery_unknown"
            else "skipped_already_sent"
        )
    return reason


def stage_bulk_resend_log(
    session: AsyncSession,
    log: WhatsAppMessageLogModel,
    state: WhatsAppRecipientMessageStateModel,
    logs: list[WhatsAppMessageLogModel],
    batch_id: uuid.UUID,
    now: datetime,
) -> None:
    logs.append(log)
    session.add(log)
    if state.status == "failed":
        state.status = "queued"
        state.batch_id = batch_id
        state.submitted_at = None
        state.provider_status_at = None
        state.status_updated_at = now
        state.updated_at = now


async def claim_bulk_resend_rows(
    session: AsyncSession,
    group: WhatsAppBroadcastGroupModel,
    body: WhatsAppBulkResendRequest,
    recipients: list[WhatsAppBroadcastRecipientModel],
    inputs: BulkResendInputs,
) -> BulkResendClaims:
    edits = inputs.edits
    states = inputs.states
    active_statuses = inputs.active_statuses
    sources = inputs.sources
    replaced_phones = inputs.replaced_phones
    batch_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    logs: list[WhatsAppMessageLogModel] = []
    results: list[WhatsAppSendResult] = []
    by_id = {recipient.id: recipient for recipient in recipients}
    # Different lists may overlap destinations; keep the original phone lock order.
    for recipient_id in sorted(
        body.recipient_ids, key=lambda key: by_id[key].normalized_phone_number
    ):
        recipient = by_id[recipient_id]
        state = states.get(recipient.id)
        reason = recipient_skip_reason(
            message_type=body.message_type,
            recipient=recipient,
            state=state,
            active_statuses=active_statuses.get(recipient.id, set()),
            replaced_phones=replaced_phones,
        )
        source = sources.get(recipient.id)
        if reason is None:
            if source is None or state is None:
                reason = "skipped_no_saved_message"
            else:
                try:
                    log = frozen_resend_log(
                        recipient=recipient,
                        source=source,
                        state=state,
                        batch_id=batch_id,
                        now=now,
                        edits=edits,
                    )
                except GroupInviteImageRequired as exc:
                    await session.rollback()
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                except (ValueError, IndexError):
                    reason = "skipped_no_saved_message"
                else:
                    if body.message_type == "welcome":
                        reason = await claim_bulk_welcome(session, group, recipient, log, batch_id)
                    if reason is not None:
                        results.append(
                            WhatsAppSendResult(
                                recipient_id=recipient.id,
                                phone_number=recipient.normalized_phone_number,
                                status=reason,
                                error_message=SKIP_MESSAGES.get(reason),
                            )
                        )
                        continue
                    stage_bulk_resend_log(session, log, state, logs, batch_id, now)
        results.append(
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status=reason or "queued",
                error_message=SKIP_MESSAGES.get(reason) if reason else None,
            )
        )
    by_result_id = {item.recipient_id: item for item in results}
    results = [by_result_id[key] for key in body.recipient_ids]
    return BulkResendClaims(batch_id, logs, results)
