"""Eligibility and immutable snapshots for explicit selected-recipient resends."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_composer import (
    BulkResendEdits,
    resolve_saved_resend_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES,
    WHATSAPP_IN_PROGRESS_STATUSES,
    WHATSAPP_STALE_CLAIM_AGE,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendDraft,
    WhatsAppBulkResendRequest,
    WhatsAppBulkResendResponse,
    WhatsAppSendResult,
)

SKIP_MESSAGES = {
    "skipped_already_sent": "This WhatsApp number already received a welcome or delivery is pending.",
    "skipped_replaced": "This person is replaced in a linked passport group.",
    "skipped_in_progress": "A message of this type is already in progress.",
    "skipped_delivery_unknown": "Previous delivery is unknown; verify it before resending.",
    "skipped_no_saved_message": "No safely saved sent or failed message is available.",
    "skipped_ineligible": "Only previously submitted or failed messages can be resent.",
}


def selection_fingerprint(body: WhatsAppBulkResendRequest) -> str:
    selected = ",".join(sorted(str(value) for value in body.recipient_ids))
    selection = f"{body.message_type}:{selected}"
    overrides = body.model_dump(
        mode="json",
        include={"message_content", "passport_intro", "header_image_id", "support_contact_ids"},
        exclude_none=True,
    )
    if overrides:
        # Keep the deployed no-edit fingerprint stable for old durable receipts.
        selection += ":" + json.dumps(overrides, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(selection.encode()).hexdigest()


def recipient_skip_reason(
    *,
    recipient: WhatsAppBroadcastRecipientModel,
    state: WhatsAppRecipientMessageStateModel | None,
    active_statuses: set[str],
    replaced_phones: set[str],
) -> str | None:
    if recipient.normalized_phone_number in replaced_phones:
        return "skipped_replaced"
    state_status = state.status if state else None
    if state_status == "delivery_unknown" or "delivery_unknown" in active_statuses:
        return "skipped_delivery_unknown"
    if state_status in WHATSAPP_IN_PROGRESS_STATUSES or active_statuses:
        return "skipped_in_progress"
    if state_status is None:
        return "skipped_no_saved_message"
    if state_status not in WHATSAPP_ACCEPTED_STATUSES | {"failed"}:
        return "skipped_ineligible"
    return None


def frozen_resend_log(
    *,
    recipient: WhatsAppBroadcastRecipientModel,
    source: WhatsAppMessageLogModel,
    state: WhatsAppRecipientMessageStateModel,
    batch_id: uuid.UUID,
    now: datetime,
    edits: BulkResendEdits | None = None,
) -> WhatsAppMessageLogModel:
    """Keep every recipient's own template, message, support block and private link.

    No common composer defaults are substituted into an existing saved message.
    Legacy snapshots are accepted only if the existing decoder verifies them.
    """
    snapshot = resolve_saved_resend_snapshot(source, edits)
    return WhatsAppMessageLogModel(
        id=uuid.uuid4(),
        normalized_phone_number=recipient.normalized_phone_number,
        batch_id=batch_id,
        broadcast_group_id=recipient.broadcast_group_id,
        recipient_id=recipient.id,
        agency_id=recipient.agency_id,
        message_type=source.message_type,
        status="queued",
        status_updated_at=now,
        provider_message_id=None,
        error_message=None,
        template_name=snapshot.template_name,
        rendered_message=snapshot.rendered_message,
        header_parameter_values=snapshot.header_parameters,
        template_parameter_values=snapshot.parameters,
        is_explicit_resend=state.status != "failed",
        created_at=now,
    )


async def expire_stale_explicit_claims(
    session: AsyncSession, *, group_id: uuid.UUID, body: WhatsAppBulkResendRequest
) -> None:
    now = datetime.now(tz=UTC)
    for previous_status, next_status, message in (
        ("queued", "failed", "Explicit resend claim expired before provider submission"),
        (
            "processing",
            "delivery_unknown",
            "Explicit resend outcome is unknown after worker interruption; another resend is blocked",
        ),
    ):
        await session.execute(
            update(WhatsAppMessageLogModel)
            .where(
                WhatsAppMessageLogModel.broadcast_group_id == group_id,
                WhatsAppMessageLogModel.recipient_id.in_(body.recipient_ids),
                WhatsAppMessageLogModel.message_type == body.message_type,
                WhatsAppMessageLogModel.is_explicit_resend.is_(True),
                WhatsAppMessageLogModel.status == previous_status,
                WhatsAppMessageLogModel.status_updated_at < now - WHATSAPP_STALE_CLAIM_AGE,
            )
            .values(status=next_status, status_updated_at=now, error_message=message)
            .execution_options(synchronize_session=False)
        )


async def selection_delivery_maps(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    body: WhatsAppBulkResendDraft,
    lock_states: bool = True,
) -> tuple[
    dict[uuid.UUID, WhatsAppRecipientMessageStateModel],
    dict[uuid.UUID, set[str]],
    dict[uuid.UUID, WhatsAppMessageLogModel],
]:
    state_statement = select(WhatsAppRecipientMessageStateModel).where(
        WhatsAppRecipientMessageStateModel.broadcast_group_id == group_id,
        WhatsAppRecipientMessageStateModel.recipient_id.in_(body.recipient_ids),
        WhatsAppRecipientMessageStateModel.message_type == body.message_type,
    )
    if lock_states:
        state_statement = state_statement.with_for_update()
    states = list((await session.execute(state_statement)).scalars().all())
    active = list(
        (
            await session.execute(
                select(WhatsAppMessageLogModel).where(
                    WhatsAppMessageLogModel.broadcast_group_id == group_id,
                    WhatsAppMessageLogModel.recipient_id.in_(body.recipient_ids),
                    WhatsAppMessageLogModel.message_type == body.message_type,
                    WhatsAppMessageLogModel.status.in_(WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    # PostgreSQL DISTINCT ON bounds history to one saved source per selected person.
    # An already accepted baseline never falls back to an unrelated failed message.
    retry_ids = [state.recipient_id for state in states if state.status == "failed"]
    sources = list(
        (
            await session.execute(
                select(WhatsAppMessageLogModel)
                .where(
                    WhatsAppMessageLogModel.broadcast_group_id == group_id,
                    WhatsAppMessageLogModel.recipient_id.in_(body.recipient_ids),
                    WhatsAppMessageLogModel.message_type == body.message_type,
                    (
                        WhatsAppMessageLogModel.status.in_(WHATSAPP_ACCEPTED_STATUSES)
                        | (
                            (WhatsAppMessageLogModel.status == "failed")
                            & WhatsAppMessageLogModel.recipient_id.in_(retry_ids)
                        )
                    ),
                )
                .distinct(WhatsAppMessageLogModel.recipient_id)
                .order_by(
                    WhatsAppMessageLogModel.recipient_id,
                    WhatsAppMessageLogModel.created_at.desc(),
                    WhatsAppMessageLogModel.status_updated_at.desc(),
                    WhatsAppMessageLogModel.id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    active_by_recipient: dict[uuid.UUID, set[str]] = {}
    stale_cutoff = datetime.now(tz=UTC) - WHATSAPP_STALE_CLAIM_AGE
    for log in active:
        log_status = log.status
        if not lock_states and log.is_explicit_resend and log.status_updated_at < stale_cutoff:
            # Preview mirrors send's stale recovery without changing any row.
            if log_status == "queued":
                continue
            if log_status == "processing":
                log_status = "delivery_unknown"
        active_by_recipient.setdefault(log.recipient_id, set()).add(log_status)
    return (
        {state.recipient_id: state for state in states},
        active_by_recipient,
        {source.recipient_id: source for source in sources},
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
