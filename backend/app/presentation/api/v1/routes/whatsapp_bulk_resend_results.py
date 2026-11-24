"""Project current selected-resend outcomes without replaying provider work."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_IN_PROGRESS_STATUSES,
    WHATSAPP_STALE_CLAIM_AGE,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendResponse,
    WhatsAppSendResult,
)


def build_response(
    *, batch_id: uuid.UUID | None, results: list[WhatsAppSendResult], replayed: bool = False
) -> WhatsAppBulkResendResponse:
    statuses = [item.status for item in results]
    return WhatsAppBulkResendResponse(
        batch_id=batch_id,
        selected=len(results),
        queued=sum(value in WHATSAPP_IN_PROGRESS_STATUSES for value in statuses),
        sent=sum(value in WHATSAPP_ACCEPTED_STATUSES for value in statuses),
        failed=statuses.count("failed"),
        delivery_unknown=statuses.count("delivery_unknown") + statuses.count("stalled"),
        skipped_in_progress=statuses.count("skipped_in_progress"),
        skipped_already_sent=statuses.count("skipped_already_sent"),
        skipped_delivery_unknown=statuses.count("skipped_delivery_unknown"),
        skipped_no_saved_message=statuses.count("skipped_no_saved_message"),
        skipped_replaced=statuses.count("skipped_replaced"),
        skipped_ineligible=statuses.count("skipped_ineligible"),
        replayed=replayed,
        results=results,
    )


async def refresh_batch_response(
    session: AsyncSession, response: WhatsAppBulkResendResponse, *, replayed: bool
) -> WhatsAppBulkResendResponse:
    if response.batch_id is None:
        return response.model_copy(update={"replayed": replayed})
    logs = list(
        (
            await session.execute(
                select(WhatsAppMessageLogModel).where(
                    WhatsAppMessageLogModel.batch_id == response.batch_id
                )
            )
        )
        .scalars()
        .all()
    )
    by_recipient = {log.recipient_id: log for log in logs}
    results = []
    stale_cutoff = datetime.now(tz=UTC) - WHATSAPP_STALE_CLAIM_AGE
    for item in response.results:
        log = by_recipient.get(item.recipient_id)
        if log is not None:
            stalled = (
                log.status in WHATSAPP_IN_PROGRESS_STATUSES and log.status_updated_at < stale_cutoff
            )
            item = item.model_copy(
                update={
                    "status": "stalled" if stalled else log.status,
                    "provider_message_id": log.provider_message_id,
                    "error_message": log.error_message
                    or (
                        "Delivery status is unknown after a worker interruption; verify before resending"
                        if stalled
                        else None
                    ),
                }
            )
        results.append(item)
    return build_response(batch_id=response.batch_id, results=results, replayed=replayed)


# Preserve existing public imports and pickle identities.
build_response.__module__ = "app.presentation.api.v1.routes.whatsapp_bulk_resend_support"
refresh_batch_response.__module__ = "app.presentation.api.v1.routes.whatsapp_bulk_resend_support"
