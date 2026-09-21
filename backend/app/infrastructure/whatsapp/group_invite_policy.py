"""Destination history guards for group invites and ordinary passport links."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import case, func, or_, select, tuple_
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
_STATUS_BY_PRIORITY = {priority: value for value, priority in _STATUS_PRIORITY.items()}


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
    return await message_phone_blocking_statuses(
        session, recipients, message_type="group_invite", current_log=current_log,
    )


async def message_phone_blocking_statuses(
    session: AsyncSession,
    recipients: Sequence[WhatsAppBroadcastRecipientModel],
    *,
    current_log: WhatsAppMessageLogModel | None = None,
    message_type: str,
    include_accepted: bool = True,
    stale_explicit_queued_cutoff: datetime | None = None,
) -> dict[uuid.UUID, str]:
    """Read destination history; a failed receipt releases only its own attempt.

    Callers taking delivery claims must hold the broadcast row lock. The worker
    excludes its own attempt, then repeats this check immediately before sending.
    Never use provider IDs/submitted_at as success: Meta may subsequently fail it.
    """
    if not recipients:
        return {}
    blocking_statuses = (
        INVITE_BLOCKING_STATUSES if include_accepted
        else INVITE_BLOCKING_STATUSES - INVITE_ACCEPTED_STATUSES
    )
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
            WhatsAppMessageLogModel.agency_id.label("agency_id"),
            WhatsAppMessageLogModel.broadcast_group_id.label("broadcast_group_id"),
            log_phone.label("phone"),
            case(
                _STATUS_PRIORITY, value=WhatsAppMessageLogModel.status, else_=-1,
            ).label("status_priority"),
        )
        .outerjoin(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.id == WhatsAppMessageLogModel.recipient_id,
        )
        .where(
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status.in_(blocking_statuses),
            tuple_(
                WhatsAppMessageLogModel.agency_id,
                WhatsAppMessageLogModel.broadcast_group_id,
                log_phone,
            ).in_(keys),
        )
    )
    if current_log is not None:
        log_query = log_query.where(WhatsAppMessageLogModel.id != current_log.id)
    if stale_explicit_queued_cutoff is not None:
        # Read-only resend previews mirror the send route's explicit claim
        # expiry; processing/unknown outcomes are never released here.
        log_query = log_query.where(or_(
            WhatsAppMessageLogModel.is_explicit_resend.is_(False),
            WhatsAppMessageLogModel.status != "queued",
            WhatsAppMessageLogModel.status_updated_at >= stale_explicit_queued_cutoff,
        ))
    state_query = (
        select(
            WhatsAppRecipientMessageStateModel.agency_id,
            WhatsAppRecipientMessageStateModel.broadcast_group_id,
            WhatsAppBroadcastRecipientModel.normalized_phone_number,
            case(
                _STATUS_PRIORITY, value=WhatsAppRecipientMessageStateModel.status, else_=-1,
            ),
        )
        .join(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.id == WhatsAppRecipientMessageStateModel.recipient_id,
        )
        .where(
            WhatsAppRecipientMessageStateModel.message_type == message_type,
            WhatsAppRecipientMessageStateModel.status.in_(blocking_statuses),
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
    # Reduce all historical attempts in the database. The result stays bounded
    # by the requested destinations even after years of retained delivery logs.
    # Worker exclusions above are applied before either source is aggregated.
    history = log_query.union_all(state_query).subquery()
    blocking_result = await session.execute(
        select(
            history.c.agency_id,
            history.c.broadcast_group_id,
            history.c.phone,
            func.max(history.c.status_priority),
        ).group_by(history.c.agency_id, history.c.broadcast_group_id, history.c.phone)
    )
    by_phone: dict[tuple[uuid.UUID, uuid.UUID, str], str] = {
        (agency_id, group_id, phone): _STATUS_BY_PRIORITY[priority]
        for agency_id, group_id, phone, priority in blocking_result.all()
    }
    result = {}
    for item in recipients:
        key = (item.agency_id, item.broadcast_group_id, item.normalized_phone_number)
        if key in by_phone:
            result[item.id] = by_phone[key]
    return result


def passport_link_block_message(status: str) -> str:
    if status in INVITE_ACCEPTED_STATUSES:
        return "A passport link has already been submitted or delivered to this number in this broadcast."
    if status == "delivery_unknown":
        return "A previous passport link has an unknown delivery outcome; another send is blocked."
    return "A passport link is already queued or being sent to this number in this broadcast."
