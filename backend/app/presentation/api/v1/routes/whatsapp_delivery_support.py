"""Delivery-ledger and webhook receipt support for WhatsApp routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)

WHATSAPP_ACCEPTED_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})
WHATSAPP_ACCEPTED_STATUS_RANK = {
    "submitted": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
}
WHATSAPP_WEBHOOK_STATUSES = frozenset({"sent", "delivered", "read", "failed"})
WHATSAPP_IN_PROGRESS_STATUSES = frozenset({"queued", "processing"})
WHATSAPP_UNCERTAIN_STATUSES = frozenset({"delivery_unknown"})
WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES = (
    WHATSAPP_IN_PROGRESS_STATUSES | WHATSAPP_UNCERTAIN_STATUSES
)
WHATSAPP_SUPPRESSED_STATUSES = (
    WHATSAPP_ACCEPTED_STATUSES | WHATSAPP_IN_PROGRESS_STATUSES | WHATSAPP_UNCERTAIN_STATUSES
)
WHATSAPP_STALE_CLAIM_AGE = timedelta(minutes=30)


def _iter_webhook_values(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for entry in payload.get("entry", []) if isinstance(payload.get("entry"), list) else []:
        for change in (
            entry.get("changes", [])
            if isinstance(entry, dict) and isinstance(entry.get("changes"), list)
            else []
        ):
            value = change.get("value") if isinstance(change, dict) else None
            if isinstance(value, dict):
                values.append(value)
    return values


def _extract_status_error(status_payload: dict[str, Any]) -> str | None:
    errors = status_payload.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    first = errors[0]
    if not isinstance(first, dict):
        return None
    provider_code = first.get("code")
    code_suffix = (
        f" ({provider_code})"
        if isinstance(provider_code, (str, int)) and not isinstance(provider_code, bool)
        else ""
    )
    return (
        "WHATSAPP_PROVIDER_DELIVERY_FAILED: "
        f"Meta reported that this message was not delivered{code_suffix}"
    )


def _parse_provider_status_at(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _is_stale_provider_status(
    current: datetime | None,
    incoming: datetime | None,
) -> bool:
    return bool(current and incoming and incoming < current)


def _apply_provider_status_to_delivery_state(
    delivery_state: WhatsAppRecipientMessageStateModel,
    *,
    provider_status: str,
    provider_status_at: datetime | None,
    now: datetime,
) -> None:
    """Apply Meta receipts without letting late events enable duplicate sends."""

    if _is_stale_provider_status(
        delivery_state.provider_status_at,
        provider_status_at,
    ):
        return
    if provider_status in WHATSAPP_ACCEPTED_STATUSES:
        current_rank = WHATSAPP_ACCEPTED_STATUS_RANK.get(delivery_state.status, -1)
        incoming_rank = WHATSAPP_ACCEPTED_STATUS_RANK[provider_status]
        if incoming_rank >= current_rank:
            delivery_state.status = provider_status
        delivery_state.submitted_at = delivery_state.submitted_at or now
        delivery_state.status_updated_at = now
        delivery_state.provider_status_at = provider_status_at or delivery_state.provider_status_at
        delivery_state.updated_at = now
    elif provider_status == "failed" and delivery_state.status not in {
        "delivered",
        "read",
    }:
        # A current-batch definitive failure is retryable until Meta reports
        # delivery. Delivered/read are monotonic and never move backwards.
        delivery_state.status = "failed"
        delivery_state.status_updated_at = now
        delivery_state.provider_status_at = provider_status_at or delivery_state.provider_status_at
        delivery_state.updated_at = now


def _apply_provider_status_to_message_log(
    log: WhatsAppMessageLogModel,
    *,
    provider_status: str,
    error_message: str | None,
    provider_status_at: datetime | None,
    now: datetime,
) -> None:
    """Keep message-log status consistent with the monotonic delivery ledger."""

    if _is_stale_provider_status(log.provider_status_at, provider_status_at):
        return
    if provider_status in WHATSAPP_ACCEPTED_STATUSES:
        current_rank = WHATSAPP_ACCEPTED_STATUS_RANK.get(log.status, -1)
        incoming_rank = WHATSAPP_ACCEPTED_STATUS_RANK[provider_status]
        if incoming_rank >= current_rank:
            log.status = provider_status
            log.status_updated_at = now
            log.provider_status_at = provider_status_at or log.provider_status_at
    elif provider_status == "failed" and log.status not in {"delivered", "read"}:
        log.status = "failed"
        log.status_updated_at = now
        log.provider_status_at = provider_status_at or log.provider_status_at
    if error_message:
        log.error_message = error_message


def _provider_status_state_predicates(
    log: WhatsAppMessageLogModel,
    *,
    provider_status: str,
) -> list[Any]:
    predicates = [
        WhatsAppRecipientMessageStateModel.recipient_id == log.recipient_id,
        WhatsAppRecipientMessageStateModel.message_type == log.message_type,
    ]
    if provider_status == "failed":
        # A failed receipt is only authoritative for the matching attempt. A
        # delayed failure from an older provider message must never release a
        # newer claim for retry.
        predicates.append(WhatsAppRecipientMessageStateModel.batch_id == log.batch_id)
    # Provider acceptance is authoritative for this recipient and message
    # type even if a later retry has already claimed the ledger. Omitting the
    # batch predicate promotes the ledger and suppresses that duplicate send
    # whenever the retry worker has not yet contacted Meta.
    return predicates


def _agency_filter(current_user: User) -> list[Any]:
    if current_user.role == UserRole.SUPER_ADMIN:
        return []
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User is not assigned to an agency"
        )
    return [WhatsAppBroadcastGroupModel.agency_id == current_user.agency_id]


def _broadcast_batch_summary_statement(
    *,
    batch_id: uuid.UUID,
    current_user: User,
    stale_cutoff: datetime,
) -> Any:
    """Build a tenant-scoped aggregate query without loading recipient details."""

    log_status = WhatsAppMessageLogModel.status
    is_in_progress = log_status.in_(WHATSAPP_IN_PROGRESS_STATUSES)
    is_stale = and_(
        is_in_progress,
        WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
    )
    is_queued = and_(
        is_in_progress,
        WhatsAppMessageLogModel.status_updated_at >= stale_cutoff,
    )
    is_sent = log_status.in_(WHATSAPP_ACCEPTED_STATUSES)
    is_uncertain = or_(
        log_status.in_({"delivery_unknown", "stalled"}),
        is_stale,
    )
    terminal_failure_statuses = ~log_status.in_(
        WHATSAPP_IN_PROGRESS_STATUSES | WHATSAPP_ACCEPTED_STATUSES | {"delivery_unknown", "stalled"}
    )
    return (
        select(
            func.count(WhatsAppMessageLogModel.id).label("total"),
            func.count(WhatsAppMessageLogModel.id).filter(is_queued).label("queued"),
            func.count(WhatsAppMessageLogModel.id).filter(is_sent).label("sent"),
            func.count(WhatsAppMessageLogModel.id)
            .filter(terminal_failure_statuses)
            .label("failed"),
            func.count(WhatsAppMessageLogModel.id).filter(is_uncertain).label("delivery_unknown"),
        )
        .select_from(WhatsAppMessageLogModel)
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id == WhatsAppMessageLogModel.broadcast_group_id,
        )
        .where(
            WhatsAppMessageLogModel.batch_id == batch_id,
            *_agency_filter(current_user),
        )
    )
