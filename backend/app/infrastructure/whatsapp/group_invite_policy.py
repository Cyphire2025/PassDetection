"""Send a group invite once per broadcast destination, including explicit retries."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)

INVITE_ACCEPTED_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})
INVITE_BLOCKING_STATUSES = INVITE_ACCEPTED_STATUSES | {"queued", "processing", "delivery_unknown"}
_STATUS_PRIORITY = {
    value: rank
    for rank, value in enumerate(
        ("queued", "processing", "delivery_unknown", "submitted", "sent", "delivered", "read")
    )
}


def group_invite_skip_reason(status: str | None) -> str | None:
    if status in INVITE_ACCEPTED_STATUSES:
        return "skipped_already_sent"
    if status == "delivery_unknown":
        return "skipped_delivery_unknown"
    if status in {"queued", "processing"}:
        return "skipped_in_progress"
    return None


def group_invite_block_message(status: str) -> str:
    if status in INVITE_ACCEPTED_STATUSES:
        return "A group invite has already been submitted or delivered to this number in this broadcast."
    if status == "delivery_unknown":
        return "A previous group invite has an unknown delivery outcome; another invite is blocked."
    return "A group invite is already queued or being sent to this number in this broadcast."


async def group_invite_blocking_statuses(
    session: AsyncSession,
    recipients: Sequence[WhatsAppBroadcastRecipientModel],
    *,
    current_log: WhatsAppMessageLogModel | None = None,
) -> dict[uuid.UUID, str]:
    """Read destination history; a failed receipt releases only its own attempt.

    Callers taking delivery claims must hold the broadcast row lock. The worker
    excludes its own attempt, then repeats this check immediately before sending.
    Never use provider IDs/submitted_at as success: Meta may subsequently fail it.
    """
    if not recipients:
        return {}
    keys = {
        (item.agency_id, item.broadcast_group_id, item.normalized_phone_number)
        for item in recipients
    }
    log_phone = func.coalesce(
        WhatsAppMessageLogModel.normalized_phone_number,
        WhatsAppBroadcastRecipientModel.normalized_phone_number,
    )
    log_query = (
        select(
            WhatsAppMessageLogModel.agency_id,
            WhatsAppMessageLogModel.broadcast_group_id,
            log_phone,
            WhatsAppMessageLogModel.status,
        )
        .outerjoin(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.id == WhatsAppMessageLogModel.recipient_id,
        )
        .where(
            WhatsAppMessageLogModel.message_type == "group_invite",
            WhatsAppMessageLogModel.status.in_(INVITE_BLOCKING_STATUSES),
            tuple_(
                WhatsAppMessageLogModel.agency_id,
                WhatsAppMessageLogModel.broadcast_group_id,
                log_phone,
            ).in_(keys),
        )
    )
    if current_log is not None:
        log_query = log_query.where(WhatsAppMessageLogModel.id != current_log.id)
    state_query = (
        select(
            WhatsAppRecipientMessageStateModel.agency_id,
            WhatsAppRecipientMessageStateModel.broadcast_group_id,
            WhatsAppBroadcastRecipientModel.normalized_phone_number,
            WhatsAppRecipientMessageStateModel.status,
        )
        .join(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.id == WhatsAppRecipientMessageStateModel.recipient_id,
        )
        .where(
            WhatsAppRecipientMessageStateModel.message_type == "group_invite",
            WhatsAppRecipientMessageStateModel.status.in_(INVITE_BLOCKING_STATUSES),
            tuple_(
                WhatsAppRecipientMessageStateModel.agency_id,
                WhatsAppRecipientMessageStateModel.broadcast_group_id,
                WhatsAppBroadcastRecipientModel.normalized_phone_number,
            ).in_(keys),
        )
    )
    if current_log is not None and not current_log.is_explicit_resend:
        # Explicit historical resends do not own the baseline state. Only this
        # normal attempt's queued/processing state can be ignored as our claim.
        state_query = state_query.where(
            or_(
                WhatsAppRecipientMessageStateModel.recipient_id != current_log.recipient_id,
                WhatsAppRecipientMessageStateModel.batch_id.is_(None),
                WhatsAppRecipientMessageStateModel.batch_id != current_log.batch_id,
                ~WhatsAppRecipientMessageStateModel.status.in_({"queued", "processing"}),
            )
        )
    by_phone: dict[tuple[uuid.UUID, uuid.UUID, str], str] = {}
    for row in [*(await session.execute(log_query)).all(), *(await session.execute(state_query)).all()]:
        agency_id, group_id, phone, delivery_status = row
        key = (agency_id, group_id, phone)
        if key not in by_phone or _STATUS_PRIORITY[delivery_status] > _STATUS_PRIORITY[by_phone[key]]:
            by_phone[key] = delivery_status
    result = {}
    for item in recipients:
        key = (item.agency_id, item.broadcast_group_id, item.normalized_phone_number)
        if key in by_phone:
            result[item.id] = by_phone[key]
    return result
